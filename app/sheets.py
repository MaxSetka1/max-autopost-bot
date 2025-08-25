# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
from typing import List, Dict, Any
import gspread
from google.oauth2.service_account import Credentials

# Доступ к таблице
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

# Имена листов
SHEET_DRAFTS  = os.getenv("GSHEET_SHEET_DRAFTS",  "drafts")
SHEET_CONTROL = os.getenv("GSHEET_SHEET_CONTROL", "control")

# Заголовки
HEADERS_DRAFTS = [
    "id","date","time","channel","format","book_id","text",
    "status","edited_text","approved_by","approved_at"
]
HEADERS_CONTROL = ["timestamp","action","date","channel","alias","status","note"]

def _client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open_ws(title: str, headers: List[str]):
    if not SHEET_KEY:
        raise RuntimeError("GSHEET_KEY is not set")
    gc = _client()
    sh = gc.open_by_key(SHEET_KEY)
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=2000, cols=len(headers) + 4)
        if headers:
            ws.update(f"A1:{chr(64+len(headers))}1", [headers])
        ws.freeze(rows=1)
    return ws

# -------------------- DRAFTS --------------------

def push_drafts(rows: List[Dict[str, Any]]):
    """Добавить черновики в конец листа drafts."""
    ws = _open_ws(SHEET_DRAFTS, HEADERS_DRAFTS)
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

def pull_all_drafts() -> List[Dict[str, Any]]:
    ws = _open_ws(SHEET_DRAFTS, HEADERS_DRAFTS)
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS_DRAFTS}
        out.append(d)
    return out

# -------------------- CONTROL --------------------

def pull_control_requests() -> List[Dict[str, Any]]:
    """
    Считать ВСЕ строки листа control как словари (по заголовкам).
    Воркер сам отфильтрует status=request.
    """
    ws = _open_ws(SHEET_CONTROL, HEADERS_CONTROL)
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS_CONTROL}
        out.append(d)
    return out

def update_control_status(date_iso: str, channel: str, new_status: str, note: str = ""):
    """
    Найти первую строку с action=generate_day, status=request и заданными date/channel
    и проставить status / note / timestamp.
    """
    ws = _open_ws(SHEET_CONTROL, HEADERS_CONTROL)
    values = ws.get_all_values()
    # заголовки в 1-й строке
    idx = {name: i for i, name in enumerate(values[0])}
    def col(name): return idx.get(name, -1)

    for r in range(1, len(values)):
        row = values[r]
        if not row or len(row) < len(HEADERS_CONTROL):
            continue
        action = row[col("action")]
        status = row[col("status")]
        d      = row[col("date")]
        ch     = row[col("channel")]
        if action == "generate_day" and status == "request" and d == date_iso and ch == channel:
            ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            values[r][col("timestamp")] = ts
            values[r][col("status")]    = new_status
            values[r][col("note")]      = note
            # Обновляем всю строку разом
            ws.update(f"A{r+1}:G{r+1}", [values[r]])
            return

# Утилита для безопасного апдейта «произвольной» строки (если понадобится)
def mark_control_done_any(date_iso: str, channel: str, note: str):
    update_control_status(date_iso=date_iso, channel=channel, new_status="done", note=note)
