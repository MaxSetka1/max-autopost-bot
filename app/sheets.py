from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

HEADERS = ["id","date","time","channel","format","book_id","text","status","edited_text","approved_by","approved_at"]

def _client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _ws():
    if not SHEET_KEY:
        raise RuntimeError("GSHEET_KEY is not set")
    gc = _client()
    sh = gc.open_by_key(SHEET_KEY)
    try:
        return sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=1000, cols=len(HEADERS)+2)
        ws.update("A1:K1", [HEADERS])
        return ws

def push_drafts(rows: list[dict]):
    """Добавить черновики в конец листа drafts."""
    ws = _ws()
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

def pull_all() -> list[dict]:
    """Считать все строки как список словарей (по заголовкам)."""
    ws = _ws()
    rows = ws.get_all_records()
    # нормализуем ключи
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS}
        out.append(d)
    return out
