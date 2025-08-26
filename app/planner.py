# app/planner.py
from __future__ import annotations
import os
import datetime as dt
from typing import List, Dict
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


def _pick_new_book() -> dict | None:
    """
    Выбираем первую книгу со статусом new из листа books.
    """
    from app.sheets import pull_books, update_book_status
    books = pull_books()
    for b in books:
        if (b.get("status") or "").lower() == "new":
            return b
    return None


def generate_day(channel_name: str, channel_alias: str, date_iso: str) -> int:
    """
    Сгенерировать черновики для всех слотов на указанную дату.
    Берём одну новую книгу из books и помечаем её как used.
    """
    tz, slots = _find_channel_slots(channel_alias, channel_name)
    if not slots:
        print(f"[DRAFTS] no slots for {channel_name}")
        return 0

    book = _pick_new_book()
    if not book:
        print(f"[DRAFTS] no new books available for {channel_name}")
        return 0

    book_id = book["file_id"]
    book_title = book.get("title") or book_id

    created = []
    for s in slots:
        fmt = s["format"]
        hhmm = s["time"]
        text = generate_from_book(channel_name, book_id, fmt)
        draft_id = upsert_draft(
            channel=channel_name, fmt=fmt, book_id=book_id,
            text=text, d=date_iso, t=hhmm
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
        print(f"[SHEETS] pushed {len(created)} rows for book {book_title}")
    except Exception as e:
        print(f"[SHEETS ERR] {e}")

    # обновляем статус книги
    from app.sheets import update_book_status
    update_book_status(book["file_id"], "used", note=f"used for {date_iso}")

    return len(created)


def poll_control():
    """
    Читает control-лист → исполняет команды (generate_day).
    """
    reqs = pull_control_requests()
    if not reqs:
        return

    for r in reqs:
        action = (r.get("action") or "").strip()
        row = r["_row"]
        date_iso = r.get("date") or dt.date.today().isoformat()
        ch_name = r.get("channel") or ""
        alias = r.get("alias") or ""

        try:
            if action == "generate_day":
                n = generate_day(ch_name, alias, date_iso)
                update_control_status(row, "done", f"created {n} drafts")
            else:
                update_control_status(row, "error", f"unknown action {action}")
        except Exception as e:
            update_control_status(row, "error", str(e))
            print(f"[CONTROL ERR] {action}: {e}")
