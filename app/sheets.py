# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
from typing import List, Dict, Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

# --- Листы и заголовки ---
HEADERS_DRAFTS = [
    "id","date","time","channel","format","book_id","text",
    "status","edited_text","approved_by","approved_at"
]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]

BOOKS_HEADERS = [
    "file_id", "title", "author", "mimeType", "url",
    "status", "updated_at", "last_used_date"
]

# ---------- базовые клиенты ----------
def _client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open():
    if not SHEET_KEY:
        raise RuntimeError("GSHEET_KEY is not set")
    gc = _client()
    return gc.open_by_key(SHEET_KEY)

# ---------- drafts ----------
def _ws_drafts():
    sh = _open()
    try:
        ws = sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=2000, cols=len(HEADERS_DRAFTS)+2)
        ws.update("A1:K1", [HEADERS_DRAFTS])
    return ws

def push_drafts(rows: List[Dict[str, Any]]):
    ws = _ws_drafts()
    values = []
    for r in rows:
        values.append([
            r.get("id",""),
            r.get("date",""),
            r.get("time",""),
            r.get("channel",""),
            r.get("format",""),
            r.get("book_id",""),
            r.get("text",""),
            r.get("status","new"),
            r.get("edited_text",""),
            r.get("approved_by",""),
            r.get("approved_at",""),
        ])
    if values:
        ws.append_rows(values, value_input_option="RAW")

def pull_all() -> List[Dict[str, Any]]:
    ws = _ws_drafts()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS_DRAFTS}
        out.append(d)
    return out

# ---------- control ----------
def _ws_control():
    sh = _open()
    try:
        ws = sh.worksheet("control")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="control", rows=1000, cols=len(CONTROL_HEADERS)+2)
        ws.update("A1:G1", [CONTROL_HEADERS])
    return ws

def pull_control_requests() -> List[Dict[str, Any]]:
    """
    Возвращает заявки со status='request'. Добавляет поле _row (номер строки).
    """
    ws = _ws_control()
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    rows = []
    for idx, line in enumerate(values[1:], start=2):
        rec = dict(zip(header, line + [""] * (len(header) - len(line))))
        if (rec.get("status") or "").strip().lower() == "request":
            rec["_row"] = idx
            rows.append(rec)
    return rows

def update_control_status(row: int, status: str, note: str = ""):
    """
    Обновляет статус и примечание в указанной строке листа control.
    """
    ws = _ws_control()
    ws.update(f"F{row}:G{row}", [[status, note]])

# ---------- books ----------
def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=2000, cols=len(BOOKS_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(BOOKS_HEADERS)-1)}1", [BOOKS_HEADERS])
    # гарантируем заголовки (если создавался вручную)
    first = ws.get_values("A1:Z1")
    if not first or first[0][:len(BOOKS_HEADERS)] != BOOKS_HEADERS:
        ws.update(f"A1:{chr(ord('A')+len(BOOKS_HEADERS)-1)}1", [BOOKS_HEADERS])
    return ws

def get_book_meta(book_id: str) -> Dict[str, str]:
    """
    Ищет книгу в листе 'books' по file_id и возвращает {title, author}.
    Если что-то не найдено — вернём пустые строки.
    """
    ws = _ws_books()
    rows = ws.get_all_records()  # [{'file_id':..., 'title':..., 'author':...}, ...]
    title, author = "", ""
    for r in rows:
        if (r.get("file_id") or "").strip() == (book_id or "").strip():
            title = (r.get("title") or "").strip()
            author = (r.get("author") or "").strip()
            break
    return {"title": title, "author": author}
