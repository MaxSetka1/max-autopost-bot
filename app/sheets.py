# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

HEADERS = ["id","date","time","channel","format","book_id","text","status","edited_text","approved_by","approved_at"]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]

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
        ws = sh.add_worksheet(title="drafts", rows=1000, cols=len(HEADERS)+2)
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
    Возвращает заявки со status='request'. Добавляет поле _row (номер строки для обновления статуса).
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

# ---------- books meta ----------
def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        # создаём пустой, если нет — заголовки как в скрипте GAS
        ws = sh.add_worksheet(title="books", rows=1000, cols=8)
        ws.update("A1:H1", [["file_id","title","author","mimeType","url","status","updated_at","note"]])
    return ws

def get_book_meta(book_id: str) -> dict:
    """
    Ищем книгу в листе books по file_id (наш book_id) и возвращаем {title, author, mimeType, url, status}.
    Если не нашли — вернём пустые строки.
    """
    if not (book_id or "").strip():
        return {"title":"","author":"","mimeType":"","url":"","status":""}

    ws = _ws_books()
    vals = ws.get_all_values()
    if not vals:
        return {"title":"","author":"","mimeType":"","url":"","status":""}

    header = vals[0]
    col_idx = {name:i for i,name in enumerate(header)}
    for row in vals[1:]:
        if len(row) <= max(col_idx.values()):  # защита от коротких строк
            continue
        if row[col_idx.get("file_id",0)] == book_id:
            return {
                "title":   row[col_idx.get("title",1)] or "",
                "author":  row[col_idx.get("author",2)] or "",
                "mimeType":row[col_idx.get("mimeType",3)] or "",
                "url":     row[col_idx.get("url",4)] or "",
                "status":  row[col_idx.get("status",5)] or "",
            }
    return {"title":"","author":"","mimeType":"","url":"","status":""}
