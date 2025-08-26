# app/sheets.py
from __future__ import annotations
import os, json, datetime as dt
from typing import List, Dict, Any
import gspread
from google.oauth2.service_account import Credentials

# --- OAuth / Open ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_KEY = os.getenv("GSHEET_KEY")

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

# =============== DRAFTS ===============

# Важно: сохраняем прежний порядок колонок, чтобы не сдвинуть уже созданный лист.
DRAFTS_HEADERS = [
    "id","date","time","channel","format","book_id","text",
    "status","edited_text","approved_by","approved_at"
]

def _ws_drafts():
    sh = _open()
    try:
        ws = sh.worksheet("drafts")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="drafts", rows=2000, cols=len(DRAFTS_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(DRAFTS_HEADERS)-1)}1", [DRAFTS_HEADERS])
    return ws

def push_drafts(rows: List[Dict[str, Any]]):
    """Добавить черновики в конец листа drafts."""
    ws = _ws_drafts()
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

def pull_all() -> List[Dict[str, Any]]:
    """Считать все строки drafts как список словарей (по заголовкам)."""
    ws = _ws_drafts()
    rows = ws.get_all_records()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = {k: r.get(k, "") for k in DRAFTS_HEADERS}
        out.append(d)
    return out

# =============== CONTROL ===============

CONTROL_HEADERS = ["timestamp","action","date","channel","alias","status","note"]

def _ws_control():
    sh = _open()
    try:
        ws = sh.worksheet("control")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="control", rows=1000, cols=len(CONTROL_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(CONTROL_HEADERS)-1)}1", [CONTROL_HEADERS])
    return ws

def pull_control_requests() -> List[Dict[str, Any]]:
    """
    Возвращает заявки со status='request'. Добавляет поле _row (номер строки для обновления статуса).
    """
    ws = _ws_control()
    values = ws.get_all_values()
    if not values:
        return []
    header = values[0]
    out: List[Dict[str, Any]] = []
    for idx, line in enumerate(values[1:], start=2):
        rec = dict(zip(header, line + [""] * (len(header) - len(line))))
        if (rec.get("status") or "").strip().lower() == "request":
            rec["_row"] = idx
            out.append(rec)
    return out

def update_control_status(row: int, status: str, note: str = ""):
    """
    Обновляет статус и примечание в указанной строке листа control.
    """
    ws = _ws_control()
    ws.update(f"F{row}:G{row}", [[status, note]])

# =============== BOOKS ===============

# Заголовки листа books. Поддерживаем автора, ссылку, mimeType.
BOOKS_HEADERS = [
    "file_id",      # ID файла на Drive (или ID Google Doc)
    "title",        # Название (читаем из Drive)
    "author",       # Автор (можно руками заполнить/исправить)
    "mimeType",
    "url",          # ссылка на файл в Drive
    "status",       # new | used
    "note",         # служебное (например: used for 2025-08-26)
    "updated_at",   # ISO-время последнего изменения записи
]

def _ws_books():
    sh = _open()
    try:
        ws = sh.worksheet("books")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="books", rows=2000, cols=len(BOOKS_HEADERS)+2)
        ws.update(f"A1:{chr(ord('A')+len(BOOKS_HEADERS)-1)}1", [BOOKS_HEADERS])
    return ws

def pull_books() -> List[Dict[str, Any]]:
    """
    Возвращает все записи из листа books как список словарей с нормализованными ключами.
    """
    ws = _ws_books()
    rows = ws.get_all_records()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = {k: r.get(k, "") for k in BOOKS_HEADERS}
        out.append(d)
    return out

def _now_iso() -> str:
    # UTC ISO8601 (секундная точность)
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def update_book_status(file_id: str, status: str, note: str = ""):
    """
    Ищет книгу по file_id и обновляет status/note/updated_at.
    Если строка не найдена — ничего не делает (без исключения).
    """
    ws = _ws_books()
    values = ws.get_all_values()
    if not values:
        return
    header = values[0]
    # индекс колонок, чтобы не зависеть от порядка
    try:
        idx_file   = header.index("file_id")
        idx_status = header.index("status")
        idx_note   = header.index("note")
        idx_upd    = header.index("updated_at")
    except ValueError:
        # если кто-то переименовал заголовки
        return

    # поиск строки
    target_row = None
    for i, line in enumerate(values[1:], start=2):
        if len(line) > idx_file and line[idx_file] == file_id:
            target_row = i
            break
    if not target_row:
        return

    ws.update(
        f"{chr(ord('A')+idx_status)}{target_row}:{chr(ord('A')+idx_upd)}{target_row}",
        [[status, note, _now_iso()]]
    )

def get_book_meta(book_id: str) -> Dict[str, Any]:
    """
    Возвращает одну запись из листа books по file_id (=book_id в пайплайне).
    Если не найдено — пустой словарь.
    """
    for b in pull_books():
        if (b.get("file_id") or "") == book_id:
            return b
    return {}
