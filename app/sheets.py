# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

# drafts + control
HEADERS = ["id","date","time","channel","format","book_id","text","status","edited_text","approved_by","approved_at"]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]

# books
BOOKS_HEADERS = ["file_id","title","author","mimeType","url","status","updated_at","note"]

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
        ws = sh.add_worksheet(title="drafts", rows=2000, cols=len(HEADERS)+2)
        ws.update("A1:K1", [HEADERS])
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
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS}
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

def pull_control_requests() -> list[dict]:
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
    ws = _ws_control()
    ws.update(f"F{row}:G{row}", [[status, note]])

# ---------- books ----------
def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=1000, cols=len(BOOKS_HEADERS)+2)
        ws.update("A1:H1", [BOOKS_HEADERS])
    return ws

def pull_books() -> list[dict]:
    ws = _ws_books()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in BOOKS_HEADERS}
        out.append(d)
    return out

def _find_book_row_by_id(file_id: str) -> int | None:
    ws = _ws_books()
    col = ws.col_values(1)  # A: file_id
    for idx, val in enumerate(col[1:], start=2):
        if (val or "").strip() == (file_id or "").strip():
            return idx
    return None

def update_book_status(file_id: str, status: str, note: str = ""):
    """
    F: status, G: updated_at (UTC), H: note
    """
    ws = _ws_books()
    row = _find_book_row_by_id(file_id)
    if not row:
        print(f"[BOOKS] file_id not found: {file_id}")
        return
    updated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    # ВНИМАНИЕ: только строки, никаких tuple
    ws.update(f"F{row}:H{row}", [[str(status), str(updated), str(note)]])

def get_book_meta(file_id: str) -> dict:
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return {}
    header = values[0]
    for line in values[1:]:
        if (line[0] or "").strip() == (file_id or "").strip():
            rec = dict(zip(header, line + [""] * (len(header) - len(line))))
            return {
                "file_id": rec.get("file_id",""),
                "title": rec.get("title",""),
                "author": rec.get("author",""),
                "mimeType": rec.get("mimeType",""),
                "url": rec.get("url",""),
                "status": rec.get("status",""),
            }
    return {}
