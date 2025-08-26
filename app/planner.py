# app/planner.py
from __future__ import annotations

import traceback
from pathlib import Path
from typing import List, Dict, Tuple
import yaml

from app.generator import generate_from_book
from app.db import upsert_draft
from app.sheets import (
    push_drafts,
    pull_control_requests,
    update_control_status,
)

# опционально: если позже добавим реальный импортер книг из Google Drive
try:
    from app.retriever import discover_drive_books  # должен вернуть int (сколько файлов найдено/обновлено)
except Exception:  # ImportError и пр.
    discover_drive_books = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
SCH_FILE = ROOT / "config" / "schedules.yaml"
SRC_FILE = ROOT / "config" / "sources.yaml"


# ---------- helpers ----------

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


def _book_id_for_channel(channel_name: str) -> str | None:
    src = _load_yaml(SRC_FILE)
    meta = (src.get("channels") or {}).get(channel_name) or {}
    if "books" in meta:
        return meta["books"].get("book_id")
    # можно расширить позже: брать «следующую готовую книгу» из БД/Drive
    return None


# ---------- main ops ----------

def generate_day(channel_name: str, channel_alias: str, date_iso: str) -> int:
    """
    Сгенерировать черновики для всех слотов канала на дату `date_iso`
    и отправить в Google Sheets (лист drafts).
    """
    _, slots = _find_channel_slots(channel_alias, channel_name)
    if not slots:
        print(f"[DRAFTS] no slots for {channel_name}")
        return 0

    book_id = _book_id_for_channel(channel_name)
    if not book_id:
        print(f"[DRAFTS] no book_id for {channel_name} in sources.yaml")
        return 0

    created_rows = []
    for s in slots:
        fmt = s["format"]
        hhmm = s["time"]

        text = generate_from_book(channel_name, book_id, fmt)
        draft_id = upsert_draft(
            channel=channel_name,
            fmt=fmt,
            book_id=book_id,
            text=text,
            d=date_iso,
            t=hhmm,
        )
        created_rows.append(
            {
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
            }
        )
        print(f"[DRAFTS] upsert {channel_name} {fmt} {date_iso} {hhmm} -> id={draft_id}")

    if created_rows:
        try:
            push_drafts(created_rows)
            print(f"[SHEETS] pushed {len(created_rows)} rows")
        except Exception as e:
            print(f"[SHEETS ERR] {e}")

    return len(created_rows)


def poll_control() -> None:
    """
    Опрос листа `control`:
      - action == 'generate' или 'generate_day' -> генерим 6 черновиков на указанную дату
      - action == 'sync' -> (опционально) синкаем книги из Drive
    После выполнения проставляем status='done' и note.
    """
    try:
        requests = pull_control_requests()
    except Exception as e:
        print(f"[CONTROL ERR] pull: {e}")
        return

    if not requests:
        return

    for req in requests:
        row_num = int(req.get("_row") or 0)
        action = (req.get("action") or "").strip().lower()
        date_iso = (req.get("date") or "").strip()
        channel = (req.get("channel") or "").strip()
        alias = (req.get("alias") or "").strip()

        try:
            if action in ("generate", "generate_day"):
                if not (channel and date_iso):
                    update_control_status(row_num, "error", "need channel + date")
                    continue
                n = generate_day(channel_name=channel, channel_alias=alias, date_iso=date_iso)
                update_control_status(row_num, "done", f"created {n} drafts")
                continue

            if action == "sync":
                if discover_drive_books:
                    try:
                        n = int(discover_drive_books())  # type: ignore
                        update_control_status(row_num, "done", f"discovered {n} files")
                    except Exception as e:
                        update_control_status(row_num, "error", f"sync failed: {e}")
                else:
                    update_control_status(row_num, "done", "sync no-op (importer not installed)")
                continue

            # неизвестное действие
            update_control_status(row_num, "error", f"unknown action: {action}")

        except Exception as e:
            print(f"[CONTROL ERR] {action}: {e}")
            print(traceback.format_exc())
            try:
                update_control_status(row_num, "error", str(e))
            except Exception:
                pass
