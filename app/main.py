# app/main.py
from __future__ import annotations

import os
import time
import yaml
import schedule
from pathlib import Path
from datetime import datetime, date as _date, date, time as dtime
from zoneinfo import ZoneInfo

from app.max_api import send_text
from app.db import init_db, add_log, fetch_draft, apply_sheet_row
from app.sheets import pull_all
from app.planner import poll_control  # опрос листа control (generate_day и пр.)

ROOT = Path(__file__).resolve().parents[1]
CFG_CH = ROOT / "config" / "channels.yaml"
CFG_SC = ROOT / "config" / "schedules.yaml"

CONTROL_POLL_SEC = int(os.getenv("CONTROL_POLL_SEC", "30"))  # как часто опрашивать control

def _load_yaml(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))

def _to_utc_hhmm(local_hhmm: str, tz_name: str) -> str:
    """
    Принимает 'HH:MM' ИЛИ 'HH:MM:SS' в локальной TZ канала
    и возвращает строку 'HH:MM:SS' в UTC (для schedule.every().day.at()).
    """
    parts = list(map(int, local_hhmm.split(":")))
    if len(parts) == 2:
        h, m = parts
        s = 0
    elif len(parts) == 3:
        h, m, s = parts
    else:
        raise ValueError(f"Bad time format: {local_hhmm}")

    today_utc: date = datetime.now(ZoneInfo("UTC")).date()
    local_dt = datetime.combine(today_utc, dtime(hour=h, minute=m, second=s), tzinfo=ZoneInfo(tz_name))
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    return utc_dt.strftime("%H:%M:%S")

def _job_send(alias: str, token_env: str, text: str, api_base: str | None = None):
    token = os.getenv(token_env)
    dry = not bool(token)  # если токена нет — DRY‑режим (печатаем, но не шлём)
    ok = send_text(token=token, alias=alias, text=text, api_base=api_base, dry_run=dry)
    tag = "DRY" if dry else "SENT"
    msg = f"[{tag}] {alias} -> {ok}"
    print(msg)
    try:
        add_log(msg)
    except Exception as e:
        print(f"[LOG ERR] {e}")

def _schedule_channel(ch: dict, slots: list, default_tz: str):
    """
    Регистрируем задачи постинга:
    - НЕ генерим текст «на лету»
    - перед отправкой подтягиваем approve/правки из Google Sheets
    - берём черновик из БД drafts (должен быть сгенерен заранее)
    """
    alias = ch["alias"]
    token_env = ch["token_env"]
    tz = ch.get("timezone") or default_tz
    api_base = os.getenv("BOT_API_BASE")
    ch_name = ch.get("name") or alias  # человеко‑читаемое имя (для drafts.channel)

    for s in slots:
        t_local = s["time"]
        fmt = s["format"]
        t_utc = _to_utc_hhmm(t_local, tz)

        def make_job(a=alias, te=token_env, api=api_base, fmt=fmt, tz=tz, ch_name=ch_name):
            def _run():
                now = _local_now(tz).strftime("%Y-%m-%d %H:%M:%S")
                today_iso = _local_now(tz).date().isoformat()

                # 1) Синхронизируем правки/статусы из Google Sheets
                try:
                    rows = pull_all()
                    for r in rows:
                        if (r.get("channel") == ch_name) and (r.get("date") == today_iso) and (r.get("format") == fmt):
                            apply_sheet_row(r)  # обновит status/edited_text по id
                except Exception as e:
                    print(f"[SYNC SHEETS ERR] {e}")

                # 2) Берём черновик на сегодня
                row = fetch_draft(channel=ch_name, fmt=fmt, d=today_iso)
                if not row:
                    print(f"[SKIP] no draft for {ch_name} {fmt} {today_iso}")
                    return

                draft_id, text, edited, status = row
                text_to_send = (edited or text or "").strip()

                # 3) Публикуем только approved
                st = (status or "new").lower()
                if st != "approved":
                    print(f"[SKIP] draft {draft_id} not approved (status={status})")
                    return
                if not text_to_send:
                    print(f"[SKIP] draft {draft_id} empty text")
                    return

                msg = f"[RUN {now} {tz}] {a} draft_id={draft_id} fmt={fmt}"
                print(msg)
                try:
                    add_log(msg)
                except Exception as e:
                    print(f"[LOG ERR] {e}")

                _job_send(alias=a, token_env=te, text=text_to_send, api_base=api)
            return _run

        schedule.every().day.at(t_utc).do(make_job())
        sched_msg = f"[SCHED] {alias} {t_local} local / {t_utc} UTC ({fmt}) [{tz}]"
        print(sched_msg)
        try:
            add_log(sched_msg)
        except Exception as e:
            print(f"[LOG ERR] {e}")

def _load_slots_for_channel(sc_cfg: dict, alias: str, name: str) -> tuple[str, list]:
    """
    Универсальный загрузчик слотов:
    - старый формат {slots: {...}}
    - новый формат {channels: [ {alias,name,slots:[]}, ...]}
    """
    tz = sc_cfg.get("timezone", "UTC")
    slots = []

    # Старый формат
    if isinstance(sc_cfg.get("slots"), dict):
        slots = sc_cfg["slots"].get(name) or sc_cfg["slots"].get(alias) or []

    # Новый формат
    if not slots:
        for chan in (sc_cfg.get("channels") or []):
            if chan.get("alias") == alias or chan.get("name") == name:
                slots = chan.get("slots") or []
                tz = chan.get("timezone", tz)
                break

    return tz, slots

def main():
    # 0) Инициализация БД
    try:
        init_db()
    except Exception as e:
        print(f"[DB INIT ERR] {e}")

    # 1) Конфиги
    ch_cfg = _load_yaml(CFG_CH)
    sc_cfg = _load_yaml(CFG_SC)
    default_tz = sc_cfg.get("default_tz", sc_cfg.get("timezone", "Europe/Moscow"))

    # 2) Регистрация задач постинга
    for ch in ch_cfg["channels"]:
        if not ch.get("enabled", True):
            continue
        alias = ch.get("alias") or ""
        name = ch.get("name") or ""
        tz, slots = _load_slots_for_channel(sc_cfg, alias, name)
        print(f"[DEBUG] loaded slots for {name or alias}: {len(slots)} (tz={tz})")
        _schedule_channel(ch, slots, tz or default_tz)

    # 3) Основной цикл воркера + опрос control
    start_msg = "[START] Worker running. Tick every second."
    print(start_msg)
    try:
        add_log(start_msg)
    except Exception as e:
        print(f"[LOG ERR] {e}")

    last_control_poll = 0.0
    while True:
        # расписание постинга
        schedule.run_pending()

        # опрос листа control раз в CONTROL_POLL_SEC
        now = time.time()
        if now - last_control_poll >= CONTROL_POLL_SEC:
            try:
                processed = poll_control()
                if processed:
                    print(f"[CONTROL] processed {processed} request(s)")
            except Exception as e:
                print(f"[CONTROL ERR] {e}")
            last_control_poll = now

        time.sleep(1)

if __name__ == "__main__":
    main()
