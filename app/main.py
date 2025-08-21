import os, time, schedule, yaml
from pathlib import Path
from datetime import datetime
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


def schedule_channel(ch: dict, slots: list, default_tz: str):
    alias = ch["alias"]
    token_env = ch["token_env"]
    tz = ch.get("timezone") or default_tz
    api_base = os.getenv("BOT_API_BASE")

    for s in slots:
        t = s["time"]
        fmt = s["format"]
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

        schedule.every().day.at(t).do(make_job())
        sched_msg = f"[SCHED] {alias} {t} ({fmt}) [{tz}]"
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
