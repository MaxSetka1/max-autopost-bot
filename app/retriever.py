from __future__ import annotations
from typing import List, Dict
import json
import numpy as np
from app.db import get_conn
from app.gpt import embed_texts

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(a.dot(b) / (na * nb))

def search_book(book_id: str, query: str, top_k: int = 5) -> List[Dict]:
    [qv] = embed_texts([query])
    q = np.array(qv, dtype=np.float32)
    rows = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chunk_id, text, emb FROM chunks WHERE book_id=%s ORDER BY chunk_id ASC;", (book_id,))
        for chunk_id, text, emb_json in cur.fetchall():
            v = np.array(json.loads(emb_json), dtype=np.float32)
            rows.append((chunk_id, text, _cosine(q, v)))
    rows.sort(key=lambda x: x[2], reverse=True)
    return [{"chunk_id": cid, "text": txt, "score": sc} for cid, txt, sc in rows[:top_k]]
