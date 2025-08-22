from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import yaml

from app.sources.rss import fetch_rss
from app.generator import generate_by_format, generate_from_book
from app.embeddings import ensure_ingested
from app.import_gdrive import ingest_book_from_drive
from app.db import count_chunks

ROOT = Path(__file__).resolve().parents[1]
SOURCES_YAML = ROOT / "config" / "sources.yaml"
BOOKS_YAML = ROOT / "config" / "books.yaml"

def make_content(channel_name: str, fmt: str) -> str:
    hours = int(os.getenv("RSS_WINDOW_HOURS", "48"))
    min_pub_dt = datetime.now(timezone.utc) - timedelta(hours=hours)

    with open(SOURCES_YAML, "r", encoding="utf-8") as f:
        src_cfg = yaml.safe_load(f) or {}

    ch_cfg = (src_cfg.get("channels") or {}).get(channel_name) or {}
    book_id = None
    urls = []

    if "books" in ch_cfg:
        book_id = ch_cfg["books"].get("book_id")
    else:
        urls = ch_cfg.get("rss") or (src_cfg.get("defaults") or {}).get("rss") or []

    if book_id:
        with open(BOOKS_YAML, "r", encoding="utf-8") as f:
            books = yaml.safe_load(f).get("books", [])
        meta = next((b for b in books if b.get("id") == book_id), {})
        title = meta.get("title") or book_id
        author = meta.get("author") or ""
        gfile = meta.get("gdrive_file_id")

        if count_chunks(book_id) == 0:
            if gfile:
                n = ingest_book_from_drive(book_id, title, author, gfile)
                print(f"[GDRIVE IMPORT] {book_id}: {n} chunks")
            else:
                notes_file = meta.get("notes_file") or f"books/{book_id}_notes.txt"
                ensure_ingested(book_id, title, author, str(ROOT / notes_file))

        return generate_from_book(channel_name, book_id, fmt)

    items = []
    if urls:
        items = fetch_rss(
            urls=urls,
            min_pub_dt=min_pub_dt,
            max_items=30,
            pick_latest_if_empty=True,
        )
    return generate_by_format(fmt, items)
