import os
import psycopg2

def _get_conn():
    dsn = os.environ["DATABASE_URL"]
    return psycopg2.connect(dsn, sslmode="require")

def get_conn():
    return _get_conn()

def init_db():
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            at TIMESTAMPTZ DEFAULT NOW(),
            message TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id SERIAL PRIMARY KEY,
            book_id TEXT NOT NULL,
            title TEXT,
            author TEXT,
            chunk_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            emb JSONB,
            hash TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_book_chunk ON chunks(book_id, chunk_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(hash);")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id SERIAL PRIMARY KEY,
            channel TEXT NOT NULL,
            format TEXT NOT NULL,
            book_id TEXT,
            text TEXT NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # новые поля для планирования и модерации
        cur.execute("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS publish_date DATE;")
        cur.execute("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS publish_time TIME;")
        cur.execute("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS edited_text TEXT;")
        cur.execute("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS approved_by TEXT;")
        cur.execute("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_pub ON drafts(channel, publish_date, publish_time);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_drafts_unique ON drafts(channel, publish_date, format);")

        conn.commit()
    print("DB: tables ensured")


def add_log(message: str):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO logs(message) VALUES (%s)", (message,))
        conn.commit()

def count_chunks(book_id: str) -> int:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE book_id=%s;", (book_id,))
        (n,) = cur.fetchone()
        return int(n or 0)

def upsert_draft(channel: str, fmt: str, book_id: str, text: str, d: str, t: str) -> int:
    """Создать/обновить черновик на дату/время. Возвращает id."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO drafts(channel, format, book_id, text, publish_date, publish_time, status)
        VALUES (%s,%s,%s,%s,%s,%s,COALESCE(%s,'new'))
        ON CONFLICT (channel, publish_date, format) DO UPDATE
          SET text=EXCLUDED.text, book_id=EXCLUDED.book_id, publish_time=EXCLUDED.publish_time
        RETURNING id;
        """, (channel, fmt, book_id, text, d, t, 'new'))
        (draft_id,) = cur.fetchone()
        conn.commit()
        return int(draft_id)

def fetch_draft(channel: str, fmt: str, d: str):
    """Вернуть один черновик (id, text, edited_text, status) на дату d."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        SELECT id, text, edited_text, status
        FROM drafts
        WHERE channel=%s AND publish_date=%s AND format=%s
        LIMIT 1;
        """, (channel, d, fmt))
        row = cur.fetchone()
        return row  # None | (id, text, edited_text, status)

def apply_sheet_row(r: dict):
    """Синхронизировать одну строку из Google Sheets в БД по id (только статус/edited_text)."""
    try:
        draft_id = int(r.get("id") or 0)
    except Exception:
        return
    if draft_id <= 0:
        return
    status = (r.get("status") or "").strip().lower() or "new"
    edited = r.get("edited_text") or None
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        UPDATE drafts
           SET status=%s,
               edited_text=%s,
               approved_by=COALESCE(%s, approved_by),
               approved_at=CASE WHEN %s='approved' THEN NOW() ELSE approved_at END
         WHERE id=%s;
        """, (status, edited, r.get("approved_by"), status, draft_id))
        conn.commit()

