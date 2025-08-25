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

        -- -- новые поля для планирования и модерации -- --
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
