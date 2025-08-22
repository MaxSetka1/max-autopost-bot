from __future__ import annotations
from app.gdrive import download_text
from app.embeddings import chunk_text, upsert_book_chunks

def ingest_book_from_drive(book_id: str, title: str, author: str, file_id: str) -> int:
    raw = download_text(file_id)
    chunks = chunk_text(raw)
    return upsert_book_chunks(book_id, title, author, chunks)
