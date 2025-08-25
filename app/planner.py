# app/planner.py
from __future__ import annotations
import time
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import yaml

from app.generator import generate_from_book
from app.db import upsert_draft
from app.sheets import (
    push_drafts,
    pull_control_requests,
    update_control_status,
    lock_control_row,
)

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "config" / "schedules.yaml"
SRC_FILE = ROOT / "config" / "sources.yaml"

def _load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def _find_channel_slots(alias: str, name: str) -> tuple[str, List[Dict]]:
    sc = _load_yaml(SCH_FILE)
    tz = sc.get("timezone", "UTC")
    slots = []
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
        draft_id = upsert_draft(channel=channel_name, fmt=fmt, book_id=book_id, text=text, d=date_iso, t=hhmm)
        created.append({
            "id": draft_id,
            "date": date_iso,
            "time": hhmm,
            "channel": channel_name,
            "alias": channel_alias,
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

# --------- опрос вкладки control ---------

def poll_control(interval_sec: int = 20):
    """
    Раз в interval_sec секунд:
      - находит строки control со status='request'
      - сразу ставит 'processing'
      - выполняет действие
      - по результату проставляет 'done' или 'error: ...'
    """
    last_seen = set()  # (timestamp, action, date, channel) — чтобы не дёргать одну и ту же строку между апдейтами
    print(f"[CONTROL] polling every {interval_sec}s")
    while True:
        try:
            rows = pull_control_requests()
            # индекс строки в таблице = позиция + 2 (т.к. есть заголовки, а get_all_records() их съедает)
            for i, r in enumerate(rows, start=2):
                status = (r.get("status") or "").strip().lower()
                action = (r.get("action") or "").strip()
                date_iso = (r.get("date") or "").strip()
                channel  = (r.get("channel") or "").strip()
                alias    = (r.get("alias") or "").strip()

                key = (r.get("timestamp"), action, date_iso, channel)

                if status != "request":
                    continue
                if key in last_seen:
                    continue

                # заблокировали строку, чтобы не обработать повторно
                lock_control_row(i, note="processing...")
                last_seen.add(key)

                try:
                    if action == "generate_day":
                        n = generate_day(channel_name=channel, channel_alias=alias, date_iso=date_iso)
                        update_control_status(i, status="done", note=f"generated {n} drafts")
                        print(f"[CONTROL] generate_day {channel} {date_iso}: {n}")
                    else:
                        update_control_status(i, status="error", note=f"unknown action: {action}")
                except Exception as e:
                    update_control_status(i, status="error", note=str(e))
                    print(f"[CONTROL ERR] {action}: {e}")

        except Exception as e:
            print(f"[CONTROL LOOP ERR] {e}")

        time.sleep(interval_sec)
