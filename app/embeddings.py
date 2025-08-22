from __future__ import annotations
import re, hashlib
from typing import List
from pathlib import Path
from app.db import get_conn, count_chunks
from app.gpt import embed_texts

def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def chunk_text(text: str, target_chars: int = 1200, overlap: int = 200) -> List[str]:
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, buf = [], ""
    for p in parts:
        if len(buf) + len(p) + 1 <= target_chars:
            buf = (buf + "\n\n" + p).strip() if buf else p
        else:
            if buf:
                chunks.append(buf)
            tail = buf[-overlap:] if buf else ""
            buf = (tail + "\n\n" + p).strip()
    if buf:
        chunks.append(buf)
    return chunks

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def json_dumps_float(arr: List[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in arr) + "]"

def upsert_book_chunks(book_id: str, title: str, author: str, chunks: List[str]) -> int:
    texts = [_normalize_ws(c) for c in chunks]
    embs = embed_texts(texts)
    with get_conn() as conn, conn.cursor() as cur:
        for i, (t, e) in enumerate(zip(texts, embs), start=1):
            h = _sha1(f"{book_id}:{i}:{t[:64]}")
            cur.execute(
                """
                INSERT INTO chunks(book_id, title, author, chunk_id, text, emb, hash)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (book_id, chunk_id) DO UPDATE
                  SET text = EXCLUDED.text, emb = EXCLUDED.emb, hash = EXCLUDED.hash
                """,
                (book_id, title, author, i, t, json_dumps_float(e), h),
            )
        conn.commit()
    return len(chunks)

def ingest_from_file(book_id: str, title: str, author: str, path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    chunks = chunk_text(raw)
    return upsert_book_chunks(book_id, title, author, chunks)

def ensure_ingested(book_id: str, title: str, author: str, notes_path: str) -> None:
    if count_chunks(book_id) > 0:
        return
    p = Path(notes_path)
    if p.exists():
        n = ingest_from_file(book_id, title, author, str(p))
        print(f"[INGEST] {book_id}: {n} chunks")
    else:
        print(f"[INGEST SKIP] notes file not found: {notes_path}")
