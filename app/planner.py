# app/planner.py
from __future__ import annotations

import yaml
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo

from app.generator import generate_from_book
from app.sheets import push_drafts
from app.db import add_log

ROOT = Path(__file__).resolve().parents[1]
CFG_CH = ROOT / "config" / "channels.yaml"
CFG_SC = ROOT / "config" / "schedules.yaml"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_slots_for_channel(sc_cfg: dict, alias: str, name: str) -> tuple[str, List[Dict[str, Any]]]:
    """
    Универсальный загрузчик слотов (старый/новый формат schedules.yaml).
    Возвращает (timezone, slots).
    """
    tz = sc_cfg.get("timezone", sc_cfg.get("default_tz", "Europe/Moscow"))
    slots: List[Dict[str, Any]] = []

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


def _date_iso_in_tz(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).date().isoformat()


def _book_id_for_channel(ch_cfg: dict, channel_name: str) -> str:
    """
    Берём book_id прямо из channels.yaml: channel.book_id
    (раньше было sources.yaml; теперь храним в одном месте).
    """
    for ch in ch_cfg.get("channels", []):
        if ch.get("name") == channel_name:
            bid = ch.get("book_id") or ch.get("source") or ""
            return bid
    return ""


def generate_day(channel_name: str, channel_alias: str, date_iso: str | None = None) -> int:
    """
    Сгенерировать все форматы на указанный день для одного канала,
    положить строки в Google Sheets (лист drafts) без дублей.
    Возвращает количество записанных строк.
    """
    ch_cfg = _load_yaml(CFG_CH)
    sc_cfg = _load_yaml(CFG_SC)

    book_id = _book_id_for_channel(ch_cfg, channel_name)
    if not book_id:
        msg = f"[DRAFTS] no book_id/source for {channel_name} in channels.yaml"
        print(msg)
        try:
            add_log(msg)
        except Exception:
            pass
        return 0

    tz, slots = _get_slots_for_channel(sc_cfg, channel_alias, channel_name)
    if not slots:
        msg = f"[DRAFTS] no slots for {channel_name}"
        print(msg)
        try:
            add_log(msg)
        except Exception:
            pass
        return 0

    day = date_iso or _date_iso_in_tz(tz)

    rows: List[Dict[str, Any]] = []
    for s in slots:
        fmt = s["format"]
        t_local = s["time"]  # HH:MM
        try:
            text = generate_from_book(channel_name, book_id, fmt)
        except Exception as e:
            text = f"⏳ Генерация временно недоступна ({e})"

        rows.append({
            "id": "",                 # в Sheets оставляем пустым
            "date": day,
            "time": t_local,
            "channel": channel_name,
            "format": fmt,
            "book_id": book_id,
            "text": text,
            "status": "new",
            "edited_text": "",
            "approved_by": "",
            "approved_at": "",
        })
        print(f"[DRAFTS] upsert {channel_name} {fmt} {day} -> queued")

    # Пишем в Sheets ИДЕМПОТЕНТНО (замена по channel+date)
    try:
        push_drafts(rows)
        msg = f"[SHEETS] pushed {len(rows)} rows for {channel_name} {day}"
        print(msg)
        try:
            add_log(msg)
        except Exception:
            pass
    except Exception as e:
        print(f"[SHEETS ERR] {e}")

    # финальный лог
    try:
        add_log(f"[DRAFTS] generated {len(rows)} for {channel_name} {day}")
    except Exception:
        pass

    return len(rows)
