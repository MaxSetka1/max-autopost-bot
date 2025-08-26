# app/sheets.py
from __future__ import annotations
import os
import json
import datetime as dt
from typing import List, Dict
import gspread
from google.oauth2.service_account import Credentials

# --- Google Sheets auth / open ------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

# headers
DRAFTS_HEADERS  = ["id","date","time","channel","format","book_id","text","status","edited_text","approved_by","approved_at"]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]
BOOKS_HEADERS   = ["file_id","title","mimeType","url","status","updated_at","note"]  # note добавили

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

# --- helpers ------------------------------------------------------------------

def _ensure_headers(ws, headers: List[str]):
    """Гарантирует первую строку с заголовками и фиксирует её."""
    first = ws.get_values("A1:1") or [[]]
    row = first[0] if first else []
    need = (len(row) < len(headers)) or any((i >= len(row) or row[i] != h) for i, h in enumerate(headers))
    if need:
        ws.update(f"A1:{gspread.utils.rowcol_to_a1(1, len(headers))}", [headers])
        ws.freeze(rows=1)

def _find_col_indexes(header: List[str]) -> Dict[str, int]:
    """Карта: имя_колонки -> индекс (0-based)."""
    return {h: i for i, h in enumerate(header)}

# --- drafts -------------------------------------------------------------------

def _ws_drafts():
    sh = _open()
    try:
        ws = sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=2000, cols=len(DRAFTS_HEADERS)+2)
    _ensure_headers(ws, DRAFTS_HEADERS)
    return ws

def push_drafts(rows: List[dict]):
    """Добавить черновики в конец листа drafts (bulk append)."""
    ws = _ws_drafts()
    values = []
    for r in rows:
        values.append([
            r.get("id",""), r.get("date",""), r.get("time",""), r.get("channel",""),
            r.get("format",""), r.get("book_id",""), r.get("text",""),
            r.get("status","new"), r.get("edited_text",""), r.get("approved_by",""), r.get("approved_at",""),
        ])
    if values:
        ws.append_rows(values, value_input_option="RAW")

def pull_all() -> List[dict]:
    """Считать все строки drafts как список словарей (по заголовкам)."""
    ws = _ws_drafts()
    rows = ws.get_all_records()
    out: List[dict] = []
    for r in rows:
        d = {k: r.get(k, "") for k in DRAFTS_HEADERS}
        out.append(d)
    return out

# --- control ------------------------------------------------------------------

def _ws_control():
    sh = _open()
    try:
        ws = sh.worksheet("control")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="control", rows=1000, cols=len(CONTROL_HEADERS)+2)
    _ensure_headers(ws, CONTROL_HEADERS)
    return ws

def pull_control_requests() -> List[dict]:
    """
    Возвращает заявки из control со status='request'.
    Добавляет служебное поле _row (номер строки для обновления).
    """
    ws = _ws_control()
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    rows: List[dict] = []
    for idx, line in enumerate(values[1:], start=2):  # строки в Sheets начинаются с 1; плюс заголовок
        if len(line) < len(header):
            line = line + [""]*(len(header)-len(line))
        rec = dict(zip(header, line))
        if (rec.get("status") or "").strip().lower() == "request":
            rec["_row"] = idx
            rows.append(rec)
    return rows

def update_control_status(row: int, status: str, note: str = ""):
    """Обновляет status и note в указанной строке листа control."""
    ws = _ws_control()
    header = ws.row_values(1)
    idx = _find_col_indexes(header)
    col_status = idx.get("status", 5) + 1  # 1-based
    col_note   = idx.get("note",   6) + 1
    rng = f"{gspread.utils.rowcol_to_a1(row, col_status)}:{gspread.utils.rowcol_to_a1(row, col_note)}"
    ws.update(rng, [[status, note]])

# --- books --------------------------------------------------------------------

def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=2000, cols=len(BOOKS_HEADERS)+2)
    _ensure_headers(ws, BOOKS_HEADERS)
    return ws

def pull_books() -> List[dict]:
    """
    Считывает все записи из листа books как список словарей.
    Ожидаемые колонки: BOOKS_HEADERS.
    """
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    rows: List[dict] = []
    for line in values[1:]:
        if not any(line):
            continue
        if len(line) < len(header):
            line = line + [""]*(len(header)-len(line))
        rec = dict(zip(header, line))
        rows.append({k: rec.get(k, "") for k in BOOKS_HEADERS})
    return rows

def update_book_status(file_id: str, status: str, note: str = ""):
    """
    Ищет книгу по file_id и обновляет status, updated_at и note.
    Если книги нет — тихо выходим.
    """
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return
    header = values[0]
    idx = _find_col_indexes(header)

    col_file   = idx.get("file_id", 0) + 1
    col_status = idx.get("status",  5) + 1
    col_upd    = idx.get("updated_at", 6) + 1
    col_note   = idx.get("note",    7) + 1

    target_row = None
    for r_i, line in enumerate(values[1:], start=2):
        if len(line) >= col_file and line[col_file-1] == file_id:
            target_row = r_i
            break

    if target_row is None:
        return

    today = dt.date.today().isoformat()
    rng = f"{gspread.utils.rowcol_to_a1(target_row, col_status)}:{gspread.utils.rowcol_to_a1(target_row, col_note)}"
    ws.update(rng, [[status, today, note]])
