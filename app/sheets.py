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

# Новый таб библиотеки:
BOOKS_HEADERS = ["file_id","title","status","last_used_date"]  # status: new|used, last_used_date: YYYY-MM-DD


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
        ws = sh.add_worksheet(title="drafts", rows=2000, cols=len(HEADERS) + 2)
        ws.update("A1:K1", [HEADERS])
        ws.freeze(rows=1)
        return ws

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
    - Если есть совпадение по id -> обновляем.
    - Иначе, если совпадает (date,time,channel,format) -> обновляем.
    - Иначе -> добавляем.
    """
    ws = _ws_drafts()

    existing = ws.get_all_records()
    by_id: dict[str, int] = {}
    by_key: dict[tuple[str,str,str,str], int] = {}
    for i, rec in enumerate(existing, start=2):
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

    updates = []
    appends = []

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

    for a1, vals in updates:
        ws.update(a1, vals, value_input_option="RAW")
    if appends:
        ws.append_rows(appends, value_input_option="RAW")


def pull_all() -> list[dict]:
    ws = _ws_drafts()
    rows = ws.get_all_records()
    return [{k: r.get(k, "") for k in HEADERS} for r in rows]


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

    try:
        first = ws.get("A1:G1")[0]
    except Exception:
        first = []
    if first != CONTROL_HEADERS:
        ws.update("A1:G1", [CONTROL_HEADERS])
        ws.freeze(rows=1)
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


# ---------- books (новое) ----------
def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=2000, cols=len(BOOKS_HEADERS) + 2)
        ws.update("A1:D1", [BOOKS_HEADERS])
        ws.freeze(rows=1)
        return ws

    try:
        first = ws.get("A1:D1")[0]
    except Exception:
        first = []
    if first != BOOKS_HEADERS:
        ws.update("A1:D1", [BOOKS_HEADERS])
        ws.freeze(rows=1)
    return ws


def pull_books() -> list[dict]:
    """Читаем все книги как list[dict] с ключами BOOKS_HEADERS."""
    ws = _ws_books()
    rows = ws.get_all_records()
    out = []
    for r in rows:
        d = {k: (r.get(k, "") or "").strip() for k in BOOKS_HEADERS}
        out.append(d)
    return out


def mark_book_used(file_id: str, date_iso: str):
    """Ставит status=used и last_used_date=date_iso для указанного file_id."""
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return
    header = values[0]
    for idx, line in enumerate(values[1:], start=2):
        rec = dict(zip(header, line + [""] * (len(header) - len(line))))
        if (rec.get("file_id") or "").strip() == file_id:
            # обновляем C(status) и D(last_used_date)
            ws.update(f"C{idx}:D{idx}", [["used", date_iso]])
            break
