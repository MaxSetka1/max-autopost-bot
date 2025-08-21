import os, time, schedule, yaml
from pathlib import Path
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo

from app.max_api import send_text
from app.db import init_db, add_log  # <-- БД: создаём таблицы и пишем логи

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
    dry = not bool(token)
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

    # Берём «сегодня» по UTC, чтобы корректно учесть смещения/DST
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
        # Конвертируем локальное время канала -> UTC для планировщика
        t_utc = _to_utc_hhmm(t_local, tz)

        sample = {
            "quote": "«Вы — результат того, что делаете каждый день». Читай.Делай!",
            "summary5": "5 идей из книги дня...",
            "practice": "Приём недели: правило 2 минут.",
            "card": "Карточка: одна мысль — одно действие. #ЧитайДелай",
        }.get(fmt, "Пост по расписанию.")

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

        # Планируем по UTC (локальное время процесса на Heroku — это UTC)
        schedule.every().day.at(t_utc).do(make_job())

        sched_msg = f"[SCHED] {alias} {t_local} local / {t_utc} UTC ({fmt}) [{tz}]"
        print(sched_msg)
        try:
            add_log(sched_msg)
        except Exception as e:
            print(f"[LOG ERR] {e}")


def main():
    # 1) Гарантируем, что таблицы БД созданы (posts, logs)
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
        slots = sc_cfg["slots"].get(ch["name"], [])
        schedule_channel(ch, slots, default_tz)

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
