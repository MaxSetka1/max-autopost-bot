from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

def _client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def push_drafts(rows: list[dict]):
    """Append строки в лист 'drafts'. rows — список словарей по нашим колонкам."""
    if not SHEET_KEY:
        print("[Sheets] GSHEET_KEY is not set, skip push")
        return
    gc = _client()
    sh = gc.open_by_key(SHEET_KEY)
    ws = sh.worksheet("drafts")
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
    ws.append_rows(values, value_input_option="RAW")

def pull_rows() -> list[dict]:
    """Считать все строки из листа 'drafts' как список словарей (по заголовкам)."""
    if not SHEET_KEY:
        return []
    gc = _client()
    sh = gc.open_by_key(SHEET_KEY)
    ws = sh.worksheet("drafts")
    return ws.get_all_records()  # [{'id':..., 'date':...}, ...]
