import os
import time
import schedule
import yaml
from pathlib import Path
from datetime import datetime, date as _date, date, time as dtime
from zoneinfo import ZoneInfo

from app.max_api import send_text
from app.db import init_db, add_log, fetch_draft, apply_sheet_row
from app.sheets import pull_all
from app.planner import generate_day  # ночная (или разовая) генерация черновиков из книги

ROOT = Path(__file__).resolve().parents[1]
CFG_CH = ROOT / "config" / "channels.yaml"
CFG_SC = ROOT / "config" / "schedules.yaml"


def load_yaml(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def local_now(tz: str):
    return datetime.now(ZoneInfo(tz))


def job_send(alias: str, token_env: str, text: str, api_base: str | None = None):
    token = os.getenv(token_env)
    dry = not bool(token)  # если токена нет — DRY-режим (печатаем, но не шлём)
    ok = send_text(token=token, alias=alias, text=text, api_base=api_base, dry_run=dry)
    tag = "DRY" if dry else "SENT"
    msg = f"[{tag}] {alias} -> {ok}"
    print(msg)
    try:
        add_log(msg)
    except Exception as e:
        print(f"[LOG ERR] {e}")


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


def schedule_channel(ch: dict, slots: list, default_tz: str):
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
    ch_name = ch.get("name") or alias  # человеко‑читаемое имя (для drafts/channel)

    for s in slots:
        t_local = s["time"]
        fmt = s["format"]

        # 1) Конверсия локального времени в UTC — Heroku в UTC
        t_utc = _to_utc_hhmm(t_local, tz)

        # 2) Фабрика задачи постинга
        def make_job(a=alias, te=token_env, api=api_base, fmt=fmt, tz=tz, ch_name=ch_name):
            def _run():
                now = local_now(tz).strftime("%Y-%m-%d %H:%M:%S")
                today_iso = local_now(tz).date().isoformat()

                # 2.1) Синхронизация approve/edited из Google Sheets в БД
                try:
                    rows = pull_all()  # все строки листа drafts (по заголовкам)
                    for r in rows:
                        if (r.get("channel") == ch_name) and (r.get("date") == today_iso) and (r.get("format") == fmt):
                            apply_sheet_row(r)  # обновит status/edited_text по id
                except Exception as e:
                    print(f"[SYNC SHEETS ERR] {e}")

                # 2.2) Достаём черновик на сегодня из БД
                row = fetch_draft(channel=ch_name, fmt=fmt, d=today_iso)
                if not row:
                    print(f"[SKIP] no draft for {ch_name} {fmt} {today_iso}")
                    return
                draft_id, text, edited, status = row
                text_to_send = (edited or text or "").strip()

                # 2.3) Публикуем только approved
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

                job_send(alias=a, token_env=te, text=text_to_send, api_base=api)
            return _run

        # 3) Регистрируем задачу по UTC
        schedule.every().day.at(t_utc).do(make_job())

        sched_msg = f"[SCHED] {alias} {t_local} local / {t_utc} UTC ({fmt}) [{tz}]"
        print(sched_msg)
        try:
            add_log(sched_msg)
        except Exception as e:
            print(f"[LOG ERR] {e}")


def _load_slots_for_channel(sc_cfg: dict, alias: str, name: str):
    """
    Универсальный загрузчик слотов:
    - старый формат {slots: {...}}
    - новый формат {channels: [ {alias,name,slots:[]}, ...]}
    """
    tz = sc_cfg.get("timezone", "UTC")
    slots = []

    # Старый формат:
    if isinstance(sc_cfg.get("slots"), dict):
        slots = sc_cfg["slots"].get(name) or sc_cfg["slots"].get(alias) or []

    # Новый формат:
    if not slots:
        for chan in (sc_cfg.get("channels") or []):
            if chan.get("alias") == alias or chan.get("name") == name:
                slots = chan.get("slots") or []
                tz = chan.get("timezone", tz)
                break

    return tz, slots


def main():
    # 1) Гарантируем таблицы в БД
    try:
        init_db()
    except Exception as e:
        print(f"[DB INIT ERR] {e}")

    # 2) Загружаем конфиги
    ch_cfg = load_yaml(CFG_CH)
    sc_cfg = load_yaml(CFG_SC)

    default_tz = sc_cfg.get("default_tz", sc_cfg.get("timezone", "Europe/Moscow"))

    # 2.1) (опционально) сгенерировать черновики на сегодня при старте
    # Включить через Config Var: GENERATE_AT_START=true (для тестов/демо)
    if os.getenv("GENERATE_AT_START", "false").lower() == "true":
        today_iso = _date.today().isoformat()
        for ch in ch_cfg["channels"]:
            if not ch.get("enabled", True):
                continue
            alias = ch.get("alias") or ""
            name = ch.get("name") or ""
            try:
                n = generate_day(channel_name=name, channel_alias=alias, date_iso=today_iso)
                print(f"[DRAFTS] generated {n} for {name} {today_iso}")
            except Exception as e:
                print(f"[DRAFTS ERR] {name}: {e}")

    # 3) Регистрируем задачи постинга по расписанию
    for ch in ch_cfg["channels"]:
        if not ch.get("enabled", True):
            continue
        alias = ch.get("alias") or ""
        name = ch.get("name") or ""
        tz, slots = _load_slots_for_channel(sc_cfg, alias, name)
        print(f"[DEBUG] loaded slots for {name or alias}: {len(slots)} (tz={tz})")
        schedule_channel(ch, slots, tz or default_tz)

    # 4) Основной цикл воркера
    start_msg = "[START] Worker running. Tick every second."
    print(start_msg)
    try:
        add_log(start_msg)
    except Exception as e:
        print(f"[LOG ERR] {e}")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
