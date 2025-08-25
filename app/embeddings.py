from __future__ import annotations
import re, hashlib, os
from typing import List
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
    # Ограничим количество чанков на импорт (MVP/без биллинга)
    cap = int(os.getenv("EMBED_MAX_CHUNKS", "30"))
    return chunks[:cap]

def _sha1(s: str) -> str:
    import hashlib as _h
    return _h.sha1(s.encode("utf-8")).hexdigest()

def json_dumps_float(arr: List[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in arr) + "]"

def _batch_iter(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def upsert_book_chunks(book_id: str, title: str, author: str, chunks: List[str]) -> int:
    texts = [_normalize_ws(c) for c in chunks]
    batch = int(os.getenv("EMBED_BATCH_SIZE", "16"))
    inserted = 0
    with get_conn() as conn, conn.cursor() as cur:
        for part in _batch_iter(texts, batch):
            embs = embed_texts(part)  # уже с ретраями/фолбэком
            for i_off, (t, e) in enumerate(zip(part, embs), start=inserted + 1):
                h = _sha1(f"{book_id}:{i_off}:{t[:64]}")
                cur.execute(
                    """
                    INSERT INTO chunks(book_id, title, author, chunk_id, text, emb, hash)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (book_id, chunk_id) DO UPDATE
                      SET text = EXCLUDED.text, emb = EXCLUDED.emb, hash = EXCLUDED.hash
                    """,
                    (book_id, title, author, i_off, t, json_dumps_float(e), h),
                )
            inserted += len(part)
        conn.commit()
    return inserted

def ingest_from_file(book_id: str, title: str, author: str, path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    chunks = chunk_text(raw)
    return upsert_book_chunks(book_id, title, author, chunks)

def ensure_ingested(book_id: str, title: str, author: str, notes_path: str) -> None:
    if count_chunks(book_id) > 0:
        return
    import os
    if os.path.exists(notes_path):
        n = ingest_from_file(book_id, title, author, notes_path)
        print(f"[INGEST] {book_id}: {n} chunks")
    else:
        print(f"[INGEST SKIP] notes file not found: {notes_path}")
