# app/sheets.py
from __future__ import annotations
import os, json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

HEADERS = [
    "id","date","time","channel","format","book_id","text",
    "status","edited_text","approved_by","approved_at"
]
CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]


# ---------- auth / open ----------
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
    return _client().open_by_key(SHEET_KEY)


# ---------- drafts ----------
def _ws_drafts():
    sh = _open()
    try:
        ws = sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=1000, cols=len(HEADERS) + 2)
        ws.update("A1:K1", [HEADERS])
        ws.freeze(rows=1)
        return ws

    # гарантируем правильные заголовки
    try:
        first = ws.get("A1:K1")[0]
    except Exception:
        first = []
    if first != HEADERS:
        ws.update("A1:K1", [HEADERS])
        ws.freeze(rows=1)
    return ws


def push_drafts(rows: list[dict]):
    """
    UPSERT в лист 'drafts'.
    - Если есть совпадение по id -> обновляем строку.
    - Иначе, если совпадает (date,time,channel,format) -> обновляем.
    - Иначе -> добавляем новую строку.
    """
    ws = _ws_drafts()

    # читаем все записи как dict и строим индексы
    existing = ws.get_all_records()  # без заголовка
    by_id: dict[str, int] = {}
    by_key: dict[tuple[str,str,str,str], int] = {}

    for i, rec in enumerate(existing, start=2):  # данные начинаются со 2-й строки
        rid = str(rec.get("id") or "").strip()
        key = (
            str(rec.get("date") or "").strip(),
            str(rec.get("time") or "").strip(),
            str(rec.get("channel") or "").strip(),
            str(rec.get("format") or "").strip(),
        )
        if rid:
            by_id[rid] = i
        by_key[key] = i

    def row_values(d: dict):
        return [
            d.get("id",""),
            d.get("date",""),
            d.get("time",""),
            d.get("channel",""),
            d.get("format",""),
            d.get("book_id",""),
            d.get("text",""),
            d.get("status","new"),
            d.get("edited_text",""),
            d.get("approved_by",""),
            d.get("approved_at",""),
        ]

    updates: list[tuple[str, list[list[str]]]] = []  # (A1range, [[vals]])
    appends: list[list[str]] = []

    for r in rows:
        rid = str(r.get("id") or "").strip()
        key = (r.get("date",""), r.get("time",""), r.get("channel",""), r.get("format",""))
        vals = row_values(r)

        target_row = None
        if rid and rid in by_id:
            target_row = by_id[rid]
        elif key in by_key:
            target_row = by_key[key]

        if target_row:
            a1 = f"A{target_row}:K{target_row}"
            updates.append((a1, [vals]))
        else:
            appends.append(vals)

    # применяем батчем
    for a1, vals in updates:
        ws.update(a1, vals, value_input_option="RAW")
    if appends:
        ws.append_rows(appends, value_input_option="RAW")


def pull_all() -> list[dict]:
    """Считать все строки из 'drafts' как список словарей по заголовкам."""
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
        ws = sh.add_worksheet(title="control", rows=1000, cols=len(CONTROL_HEADERS) + 2)
        ws.update("A1:G1", [CONTROL_HEADERS])
        ws.freeze(rows=1)
        return ws

    # гарантируем правильные заголовки
    try:
        first = ws.get("A1:G1")[0]
    except Exception:
        first = []
    if first != CONTROL_HEADERS:
        ws.update("A1:G1", [CONTROL_HEADERS])
        ws.freeze(rows=1)
    return ws


def pull_control_requests() -> list[dict]:
    """
    Возвращает заявки со status='request'.
    Каждой записи добавляет поле _row (номер строки для последующего update).
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
    """Обновляет статус и примечание в указанной строке листа control."""
    ws = _ws_control()
    ws.update(f"F{row}:G{row}", [[status, note]])
