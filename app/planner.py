# app/planner.py
from __future__ import annotations
import traceback
import datetime as dt
from typing import List, Dict, Tuple
from pathlib import Path
import yaml

from app.generator import generate_from_book
from app.db import upsert_draft
from app.sheets import (
    push_drafts, pull_control_requests, update_control_status,
    pull_books, update_book_status
)

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "config" / "schedules.yaml"

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

def _pick_new_book() -> dict | None:
    # Берём первую книгу со статусом new (без выдумок)
    for b in pull_books():
        if (b.get("status") or "").strip().lower() == "new":
            return b
    return None

def generate_day(channel_name: str, channel_alias: str, date_iso: str) -> int:
    print(f"[GEN] start generate_day channel={channel_name} alias={channel_alias} date={date_iso}")
    tz, slots = _find_channel_slots(channel_alias, channel_name)
    if not slots:
        print(f"[GEN] no slots for {channel_name}")
        return 0

    book = _pick_new_book()
    if not book:
        print(f"[GEN] no new books for {channel_name}")
        return 0

    book_id = (book.get("file_id") or "").strip()
    book_title = (book.get("title") or book_id or "").strip()
    print(f"[GEN] picked book: id={book_id} title={book_title}")

    # 1) помечаем книгу как «в работе»
    try:
        update_book_status(str(book_id), "in_progress", note=f"started for {date_iso}")
        print(f"[BOOKS] status updated: {book_id} -> in_progress (started for {date_iso})")
    except Exception as e:
        print(f"[BOOKS WARN] can't set in_progress: {e}")
        print(traceback.format_exc())

    created_rows: List[Dict] = []
    created_count = 0

    # 2) генерим все слоты
    for s in slots:
        fmt = s["format"]
        hhmm = s["time"]
        try:
            text = generate_from_book(channel_name, book_id, fmt)
            draft_id = upsert_draft(
                channel=channel_name, fmt=fmt, book_id=book_id,
                text=text, d=date_iso, t=hhmm
            )
            created_count += 1
            created_rows.append({
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
        except Exception as e:
            print(f"[GEN ERR] slot {fmt} {hhmm}: {e}")
            print(traceback.format_exc())

    # 3) пушим в шит, если есть что пушить
    pushed_ok = False
    if created_rows:
        try:
            push_drafts(created_rows)
            pushed_ok = True
            print(f"[SHEETS] pushed {len(created_rows)} rows for book {book_title}")
        except Exception as e:
            pushed_ok = False
            print(f"[SHEETS ERR] push_drafts: {e}")
            print(traceback.format_exc())

    # 4) финализируем статус книги
    try:
        if created_count > 0 and pushed_ok:
            note = f"used for {date_iso} ({created_count} drafts)"
            update_book_status(str(book_id), "used", note=note)
            print(f"[BOOKS] status updated: {book_id} -> used ({note})")
        else:
            note = f"rollback: 0 drafts for {date_iso}" if created_count == 0 else f"rollback: push failed for {date_iso}"
            update_book_status(str(book_id), "new", note=note)
            print(f"[BOOKS] status updated: {book_id} -> new ({note})")
    except Exception as e:
        print(f"[BOOKS ERR] update_book_status(final): {e}")
        print(traceback.format_exc())

    return created_count

def poll_control():
    reqs = pull_control_requests()
    if not reqs:
        return
    for r in reqs:
        action = (r.get("action") or "").strip()
        row = r.get("_row")
        date_iso = r.get("date") or dt.date.today().isoformat()
        ch_name = r.get("channel") or ""
        alias = r.get("alias") or ""
        try:
            if action == "generate_day":
                n = generate_day(ch_name, alias, date_iso)
                update_control_status(int(row), "done", f"created {n} drafts")
            else:
                update_control_status(int(row), "error", f"unknown action {action}")
        except Exception as e:
            update_control_status(int(row), "error", str(e))
            print(f"[CONTROL ERR] {action}: {e}")
            print(traceback.format_exc())
