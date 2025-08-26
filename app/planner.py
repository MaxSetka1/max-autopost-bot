# app/planner.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Tuple
import yaml
from datetime import date as _date

from app.generator import generate_from_book
from app.db import upsert_draft
from app.sheets import push_drafts, pull_books, mark_book_used

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "config" / "schedules.yaml"
SRC_FILE = ROOT / "config" / "sources.yaml"


def _load_yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


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


def _pick_book_for_channel(channel_name: str) -> Tuple[str, str]:
    """
    Возвращает (book_id, book_title).
    Приоритет:
      1) Если в sources.yaml задан конкретный book_id — используем его.
      2) Иначе берём первую книгу из листа 'books' со status='new'.
    """
    src = _load_yaml(SRC_FILE)
    meta = (src.get("channels") or {}).get(channel_name) or {}
    # 1) конкретный book_id в sources.yaml
    if "books" in meta:
        b = meta["books"]
        if isinstance(b, dict) and b.get("book_id"):
            return b["book_id"], b.get("title", "")

    # 2) иначе — из sheets 'books'
    books = pull_books()  # [{"file_id","title","status","last_used_date"}, ...]
    for rec in books:
        if (rec.get("status") or "").lower() != "used":
            bid = rec.get("file_id") or ""
            title = rec.get("title") or ""
            if bid:
                return bid, title

    # если ничего не нашли — вернём пусто
    return "", ""


def generate_day(channel_name: str, channel_alias: str, date_iso: str) -> int:
    """
    Сгенерировать черновики на дату date_iso для всех слотов канала.
    Книгу подбираем автоматически (либо из sources.yaml, либо первая new из 'books').
    После успеха — помечаем книгу в 'books' как used.
    """
    tz, slots = _find_channel_slots(channel_alias, channel_name)
    if not slots:
        print(f"[DRAFTS] no slots for {channel_name}")
        return 0

    book_id, book_title = _pick_book_for_channel(channel_name)
    if not book_id:
        print(f"[DRAFTS] no available book for {channel_name} (sources.yaml or books sheet)")
        return 0

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

    # пушим в sheets
    try:
        push_drafts(created)
        print(f"[SHEETS] pushed {len(created)} rows")
    except Exception as e:
        print(f"[SHEETS ERR] {e}")

    # помечаем книгу как использованную
    try:
        mark_book_used(book_id, date_iso)
        print(f"[BOOKS] marked used: {book_id} on {date_iso}")
    except Exception as e:
        print(f"[BOOKS ERR] {e}")

    return len(created)
