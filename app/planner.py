from __future__ import annotations
import os
from datetime import date
from typing import List, Dict
import yaml

from app.db import get_conn
from app.generator import generate_from_book
from app.sheets import push_drafts, pull_rows

ROOT_CFG = "config"
SRC_FILE = f"{ROOT_CFG}/sources.yaml"
SCH_FILE = f"{ROOT_CFG}/schedules.yaml"

def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _get_channel_book_id(channel_name: str) -> str | None:
    src = _load_yaml(SRC_FILE)
    ch = (src.get("channels") or {}).get(channel_name) or {}
    if "books" in ch:
        return ch["books"].get("book_id")
    return None

def _get_today_slots(channel_alias: str) -> List[Dict]:
    sch = _load_yaml(SCH_FILE)
    channels = sch.get("channels") or []
    for ch in channels:
        if ch.get("alias") == channel_alias:
            return ch.get("slots") or []
    return []

def upsert_draft(channel: str, fmt: str, book_id: str, text: str, d: date, t: str) -> int:
    """Создать/обновить черновик. Возвращает id."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO drafts(channel, format, book_id, text, publish_date, publish_time, status)
        VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, 'new'))
        ON CONFLICT (channel, publish_date, format) DO UPDATE
          SET text = EXCLUDED.text,
              book_id = EXCLUDED.book_id,
              publish_time = EXCLUDED.publish_time
        RETURNING id;
        """, (channel, fmt, book_id, text, d, t, 'new'))
        (draft_id,) = cur.fetchone()
        conn.commit()
        return int(draft_id)

def list_drafts_for_day(channel: str, d: date) -> List[Dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        SELECT id, publish_date, publish_time, channel, format
