import os
import time
import schedule
import yaml
from pathlib import Path
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo

from app.max_api import send_text
from app.db import init_db, add_log
from app.content import make_content  # <-- генератор чернового текста

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
    dry = not bool(token)  # если токена нет — DRY-режим
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
    alias = ch["alias"]
    token_env = ch["token_env"]
    tz = ch.get("timezone") or default_tz
    api_base = os.getenv("BOT_API_BASE")

    for s in slots:
        t_local = s["time"]
        fmt = s["format"]

        # 1) Конвертируем локальное время канала -> UTC
        t_utc = _to_utc_hhmm(t_local, tz)

        # 2) Генерация чернового контента
        sample = make_content(ch.get("name") or alias, fmt)

        # 3) Фабрика джобы
        def make_job(a=alias, te=token_env, text=sample, api=api_base, tz=tz):
            def _run():
                now = local_now(tz).strftime("%Y-%m-%d %H:%M:%S")
                msg = f"[RUN {now} {tz}] {a} {text[:40]}..."
                print(msg)
                try:
                    add_log(msg)
                except Exception as e:
                    print(f"[LOG ERR] {e}")
                job_send(alias=a, token_env=te, text=text, api_base=api)
            return _run

        # 4) Планируем по UTC
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
    # 1) Создаём таблицы
    try:
        init_db()
    except Exception as e:
        print(f"[DB INIT ERR] {e}")

    # 2) Загружаем конфиги
    ch_cfg = load_yaml(CFG_CH)
    sc_cfg = load_yaml(CFG_SC)

    default_tz = sc_cfg.get("default_tz", "Europe/Moscow")

    # 3) Регистрируем задачи по расписанию
    for ch in ch_cfg["channels"]:
        if not ch.get("enabled", True):
            continue
        alias = ch.get("alias") or ""
        name = ch.get("name") or ""
        tz, slots = _load_slots_for_channel(sc_cfg, alias, name)
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
