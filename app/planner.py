# app/planner.py
from __future__ import annotations
import os
from typing import List, Dict, Tuple
from pathlib import Path
import yaml

from app.generator import generate_from_book
from app.db import upsert_draft
from app.sheets import push_drafts, pull_control_requests, update_control_status

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "config" / "schedules.yaml"
SRC_FILE = ROOT / "config" / "sources.yaml"

def _load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def _find_channel_slots(alias: str, name: str) -> Tuple[str, List[Dict]]:
    sc = _load_yaml(SCH_FILE)
    tz = sc.get("timezone", "UTC")
    slots: List[Dict] = []
    for ch in (sc.get("channels") or []):
        if ch.get("alias") == alias or ch.get("name") == name:
            tz = ch.get("timezone", tz)
            slots = ch.get("slots") or []
            break
    return tz, slots

def _book_id_for_channel(channel_name: str) -> str | None:
    src = _load_yaml(SRC_FILE)
    meta = (src.get("channels") or {}).get(channel_name) or {}
    if "books" in meta:
        return meta["books"].get("book_id")
    return None

def generate_day(channel_name: str, channel_alias: str, date_iso: str) -> int:
    tz, slots = _find_channel_slots(channel_alias, channel_name)
    if not slots:
        print(f"[DRAFTS] no slots for {channel_name}")
        return 0

    book_id = _book_id_for_channel(channel_name)
    if not book_id:
        print(f"[DRAFTS] no book_id for {channel_name} in sources.yaml")
        return 0

    created = []
    for s in slots:
        fmt  = s["format"]
        hhmm = s["time"]
        text = generate_from_book(channel_name, book_id, fmt)
        draft_id = upsert_draft(
            channel=channel_name, fmt=fmt, book_id=book_id, text=text, d=date_iso, t=hhmm
        )
        created.append({
            "id": draft_id,
            "date": date_iso,
            "time": hhmm,
            "channel": channel_name,
            "format": fmt,
            "book_id": book_id,
            "text": text,
            "status": "new",
            "edited_text": "",
            "approved_by": "",
            "approved_at": "",
        })
        print(f"[DRAFTS] upsert {channel_name} {fmt} {date_iso} {hhmm} -> id={draft_id}")

    try:
        push_drafts(created)
        print(f"[SHEETS] pushed {len(created)} rows")
    except Exception as e:
        print(f"[SHEETS ERR] {e}")

    return len(created)

# ----------- ПОЛЛИНГ control ------------

def poll_control() -> int:
    """
    Читает лист control и обрабатывает заявки вида:
      action=generate_day, status=request
    Возвращает число обработанных заявок.
    """
    try:
        rows = pull_control_requests()
    except Exception as e:
        print(f"[CONTROL ERR] read: {e}")
        return 0

    processed = 0
    for r in rows:
        action = (r.get("action") or "").strip()
        status = (r.get("status") or "").strip()
        if action != "generate_day" or status != "request":
            continue

        date_iso = (r.get("date") or "").strip()
        channel  = (r.get("channel") or "").strip()
        alias    = (r.get("alias") or "").strip()

        if not (date_iso and channel):
            continue

        try:
            n = generate_day(channel_name=channel, channel_alias=alias, date_iso=date_iso)
            update_control_status(date_iso, channel, "done", note=f"generated {n} rows")
            processed += 1
            print(f"[CONTROL] generated {n} for {channel} {date_iso}")
        except Exception as e:
            print(f"[CONTROL ERR] generate: {e}")
    return processed
