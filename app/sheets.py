# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

DRAFT_HEADERS = ["id","date","time","channel","format","book_id","text","status","edited_text","approved_by","approved_at"]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]
BOOK_HEADERS = ["file_id","title","author","mimeType","url","status","updated_at","note"]

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
        ws = sh.add_worksheet(title="drafts", rows=1000, cols=len(DRAFT_HEADERS)+2)
        ws.update("A1:K1", [DRAFT_HEADERS])
    return ws

def push_drafts(rows: list[dict]):
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

def pull_all() -> list[dict]:
    ws = _ws_drafts()
    rows = ws.get_all_records()
    return [{k: r.get(k,"") for k in DRAFT_HEADERS} for r in rows]

# ---------- control ----------
def _ws_control():
    sh = _open()
    try:
        ws = sh.worksheet("control")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="control", rows=1000, cols=len(CONTROL_HEADERS)+2)
        ws.update("A1:G1", [CONTROL_HEADERS])
    return ws

def pull_control_requests() -> list[dict]:
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
    ws = _ws_control()
    ws.update(f"F{row}:G{row}", [[status, note]])

# ---------- books ----------
def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=1000, cols=len(BOOK_HEADERS)+2)
        ws.update("A1:H1", [BOOK_HEADERS])
    return ws

def pull_books() -> list[dict]:
    ws = _ws_books()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in BOOK_HEADERS}
        out.append(d)
    return out

def update_book_status(file_id: str, status: str, note: str = ""):
    """
    Обновляем статус книги в листе books: status(F), updated_at(G), note(H).
    """
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return
    header = values[0]
    try:
        i_file = header.index("file_id")
        i_status = header.index("status")
        i_updated = header.index("updated_at")
        i_note = header.index("note")
    except ValueError:
        raise RuntimeError("books header is incomplete")

    # ищем строку
    row_idx = None
    for idx, line in enumerate(values[1:], start=2):
        if len(line) > i_file and line[i_file] == file_id:
            row_idx = idx
            break
    if not row_idx:
        return

    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    # диапазон с F по H
    col_from = chr(ord('A') + i_status)
    col_to   = chr(ord('A') + i_note)
    ws.update(f"{col_from}{row_idx}:{col_to}{row_idx}", [[status, now, note]])

def get_book_meta(file_id: str) -> dict:
    """Возвращает {title, author, ...} по file_id из листа books."""
    ws = _ws_books()
    rows = ws.get_all_records()
    for r in rows:
        if (r.get("file_id") or "").strip() == (file_id or "").strip():
            return r
    return {}
