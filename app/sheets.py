# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")
TZ = os.getenv("DEFAULT_TZ", "Europe/Moscow")

DRAFTS_SHEET  = os.getenv("GSHEET_DRAFTS_TAB",  "drafts")
CONTROL_SHEET = os.getenv("GSHEET_CONTROL_TAB", "control")

DRAFT_HEADERS = [
    "id","date","time","channel","alias","format","book_id",
    "text","status","edited_text","approved_by","approved_at"
]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]


# ---------- base ----------
def _client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _open_sheet():
    if not SHEET_KEY:
        raise RuntimeError("GSHEET_KEY is not set")
    return _client().open_by_key(SHEET_KEY)


# ---------- drafts ----------
def _ensure_drafts_ws():
    sh = _open_sheet()
    try:
        ws = sh.worksheet(DRAFTS_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=DRAFTS_SHEET, rows=2000, cols=len(DRAFT_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(DRAFT_HEADERS)-1)}1", [DRAFT_HEADERS])
        ws.freeze(rows=1)
    first = ws.get_values(f"A1:{chr(ord('A')+len(DRAFT_HEADERS)-1)}1")
    if not first or first[0][:len(DRAFT_HEADERS)] != DRAFT_HEADERS:
        ws.update(f"A1:{chr(ord('A')+len(DRAFT_HEADERS)-1)}1", [DRAFT_HEADERS])
        ws.freeze(rows=1)
    return ws

def push_drafts(rows: list[dict]):
    ws = _ensure_drafts_ws()
    values = []
    for r in rows:
        values.append([
            r.get("id",""),
            r.get("date",""),
            r.get("time",""),
            r.get("channel",""),
            r.get("alias",""),
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
    ws = _ensure_drafts_ws()
    rows = ws.get_all_records()
    return [{k: r.get(k, "") for k in DRAFT_HEADERS} for r in rows]


# ---------- control ----------
def _ensure_control_ws():
    sh = _open_sheet()
    try:
        ws = sh.worksheet(CONTROL_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=CONTROL_SHEET, rows=500, cols=len(CONTROL_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(CONTROL_HEADERS)-1)}1", [CONTROL_HEADERS])
        ws.freeze(rows=1)
    first = ws.get_values(f"A1:{chr(ord('A')+len(CONTROL_HEADERS)-1)}1")
    if not first or first[0][:len(CONTROL_HEADERS)] != CONTROL_HEADERS:
        ws.update(f"A1:{chr(ord('A')+len(CONTROL_HEADERS)-1)}1", [CONTROL_HEADERS])
        ws.freeze(rows=1)
    return ws

def append_control(action: str, date_iso: str, channel: str, alias: str, note: str = ""):
    ws = _ensure_control_ws()
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([ts, action, date_iso, channel, alias, "request", note], value_input_option="RAW")

def pull_control_requests() -> list[dict]:
    ws = _ensure_control_ws()
    rows = ws.get_all_records()
    return [{k: r.get(k, "") for k in CONTROL_HEADERS} for r in rows]

# tolerant updater: принимает позиционные/именованные аргументы
def update_control_status(row_index_1based, status=None, note=None, **_kwargs):
    ws = _ensure_control_ws()
    if status is None: status = ""
    if note   is None: note   = ""
    col_status = CONTROL_HEADERS.index("status") + 1
    col_note   = CONTROL_HEADERS.index("note")   + 1
    ws.update_cell(row_index_1based, col_status, status)
    ws.update_cell(row_index_1based, col_note,   note)

# немедленная «блокировка» строки, чтобы не сработать повторно
def lock_control_row(row_index_1based, note="processing"):
    update_control_status(row_index_1based, status="processing", note=note)

# алиасы (если где-то используются другие имена)
def read_control() -> list[dict]:
    return pull_control_requests()

def write_control_status(row_index_1based: int, status: str, note: str = ""):
    return update_control_status(row_index_1based, status=status, note=note)
