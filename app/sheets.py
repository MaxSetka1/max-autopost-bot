from __future__ import annotations
import os, json, datetime as dt
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

HEADERS = [
    "id","date","time","channel","format","book_id",
    "text","status","edited_text","approved_by","approved_at"
]

# -------------------- auth & worksheet --------------------

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
        ws = sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=1000, cols=len(HEADERS) + 2)
        ws.update("A1:K1", [HEADERS])
    # гарантируем заголовок
    try:
        head = ws.row_values(1)
        if [h.strip() for h in head] != HEADERS:
            ws.update("A1:K1", [HEADERS])
    except Exception:
        pass
    return ws

# -------------------- I/O --------------------

def push_drafts(rows: list[dict]):
    """
    Идемпотентная запись черновиков:
    - Берёт channel и date из первого ряда
    - Удаляет все существующие строки для этой пары (channel+date)
    - Записывает новые строки одним батчем
    """
    if not rows:
        return
    ws = _ws()

    ch = rows[0].get("channel", "")
    d  = rows[0].get("date", "")

    # 1) Считываем текущие строки и фильтруем нецелевые
    existing = ws.get_all_records()  # список словарей по HEADERS
    kept = [r for r in existing if not (str(r.get("channel")) == str(ch) and str(r.get("date")) == str(d))]

    # 2) Собираем итоговый массив (шапка + оставленные + новые)
    matrix = [HEADERS]

    def _row_to_list(r: dict) -> list:
        return [
            r.get("id",""),
            r.get("date",""),
            r.get("time",""),
            r.get("channel",""),
            r.get("format",""),
            r.get("book_id",""),
            r.get("text",""),
            (r.get("status") or "new"),
            r.get("edited_text",""),
            r.get("approved_by",""),
            r.get("approved_at",""),
        ]

    for r in kept:
        # r уже с ключами из HEADERS, но приведём явно
        matrix.append(_row_to_list(r))
    for r in rows:
        matrix.append(_row_to_list(r))

    # 3) Полная перезапись листа (без дублей)
    ws.clear()
    ws.update(f"A1:K{len(matrix)}", matrix, value_input_option="RAW")

def pull_all() -> list[dict]:
    """Считать все строки как список словарей (по заголовкам)."""
    ws = _ws()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: r.get(k, "") for k in HEADERS}
        out.append(d)
    return out
