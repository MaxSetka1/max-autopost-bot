# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

# OAuth и ключ таблицы из Config Vars
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")  # ID таблицы (цифро‑буквенная строка)
TZ = os.getenv("DEFAULT_TZ", "Europe/Moscow")

# Лист с черновиками
DRAFTS_SHEET = os.getenv("GSHEET_DRAFTS_TAB", "drafts")
# Лист с управляющими командами
CONTROL_SHEET = os.getenv("GSHEET_CONTROL_TAB", "control")

# Заголовки листа drafts
DRAFT_HEADERS = [
    "id", "date", "time", "channel", "alias", "format", "book_id",
    "text", "status", "edited_text", "approved_by", "approved_at"
]

# Заголовки листа control
CONTROL_HEADERS = ["timestamp", "action", "date", "channel", "alias", "status", "note"]


# ---------- базовый клиент ----------

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
    gc = _client()
    return gc.open_by_key(SHEET_KEY)


# ---------- drafts ----------

def _ensure_drafts_ws():
    sh = _open_sheet()
    try:
        ws = sh.worksheet(DRAFTS_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=DRAFTS_SHEET, rows=2000, cols=len(DRAFT_HEADERS)+2)
        ws.update("A1:%s1" % chr(ord('A') + len(DRAFT_HEADERS) - 1), [DRAFT_HEADERS])
        ws.freeze(rows=1)
    # убедимся, что заголовки на месте
    first = ws.get_range("A1:%s1" % chr(ord('A') + len(DRAFT_HEADERS) - 1)).get_values()
    if not first or first[0][:len(DRAFT_HEADERS)] != DRAFT_HEADERS:
        ws.update("A1:%s1" % chr(ord('A') + len(DRAFT_HEADERS) - 1), [DRAFT_HEADERS])
        ws.freeze(rows=1)
    return ws

def push_drafts(rows: list[dict]):
    """
    Добавить черновики в конец листа drafts.
    Строки — словари по ключам из DRAFT_HEADERS.
    """
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
    """
    Считать все строки из листа drafts как список словарей по заголовкам.
    Нужна для синхронизации approve/edited -> БД.
    """
    ws = _ensure_drafts_ws()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in DRAFT_HEADERS}
        out.append(d)
    return out


# ---------- control ----------

def _ensure_control_ws():
    sh = _open_sheet()
    try:
        ws = sh.worksheet(CONTROL_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=CONTROL_SHEET, rows=500, cols=len(CONTROL_HEADERS)+2)
        ws.update("A1:%s1" % chr(ord('A') + len(CONTROL_HEADERS) - 1), [CONTROL_HEADERS])
        ws.freeze(rows=1)
    # заголовки
    first = ws.get_range("A1:%s1" % chr(ord('A') + len(CONTROL_HEADERS) - 1)).get_values()
    if not first or first[0][:len(CONTROL_HEADERS)] != CONTROL_HEADERS:
        ws.update("A1:%s1" % chr(ord('A') + len(CONTROL_HEADERS) - 1), [CONTROL_HEADERS])
        ws.freeze(rows=1)
    return ws

def append_control(action: str, date_iso: str, channel: str, alias: str, note: str = ""):
    """Сервисная функция: добавить строку в control c статусом request."""
    ws = _ensure_control_ws()
    ts = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(0))).isoformat()
    ws.append_row([ts, action, date_iso, channel, alias, "request", note], value_input_option="RAW")

def read_control() -> list[dict]:
    """Прочитать все строки control (как есть)."""
    ws = _ensure_control_ws()
    rows = ws.get_all_records()
    # нормализуем ключи
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in CONTROL_HEADERS}
        out.append(d)
    return out

def write_control_status(row_index_1based: int, status: str, note: str = ""):
    """
    Обновить статус и примечание в control.
    row_index_1based — индекс строки в Google Sheets (начиная с 2, т.к. 1 — заголовки).
    """
    ws = _ensure_control_ws()
    ws.update_cell(row_index_1based, CONTROL_HEADERS.index("status")+1, status)
    if note:
        ws.update_cell(row_index_1based, CONTROL_HEADERS.index("note")+1, note)
