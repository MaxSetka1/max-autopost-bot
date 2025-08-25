import os
import psycopg2

def _get_conn():
    """
    Возвращает подключение к БД Heroku Postgres.
    Heroku автоматически добавляет переменную окружения DATABASE_URL.
    """
    dsn = os.environ["DATABASE_URL"]
    return psycopg2.connect(dsn, sslmode="require")

def get_conn():
    """Публичная функция для других модулей."""
    return _get_conn()

def init_db():
    """
    Создаём таблицы, если их ещё нет.
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # логи
        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            at TIMESTAMPTZ DEFAULT NOW(),
            message TEXT
        );
        """)

        # фрагменты книг
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

        # черновики постов
        cur.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id SERIAL PRIMARY KEY,
            channel TEXT NOT NULL,
            format TEXT NOT NULL,
            book_id TEXT,
            text TEXT NOT NULL,
            status TEXT DEFAULT 'new', -- new/approved/rejected/sent
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        conn.commit()
    print("DB: tables ensured")

def add_log(message: str):
    """Записать строку в лог."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO logs(message) VALUES (%s)", (message,))
        conn.commit()

def count_chunks(book_id: str) -> int:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE book_id=%s;", (book_id,))
        (n,) = cur.fetchone()
        return int(n or 0)
