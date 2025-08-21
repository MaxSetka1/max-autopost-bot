# app/db.py
import os
import psycopg2

def _get_conn():
    """
    Возвращает подключение к БД Heroku Postgres.
    Heroku автоматически добавляет переменную окружения DATABASE_URL.
    """
    dsn = os.environ["DATABASE_URL"]  # <- берём строку подключения из Config Vars
    # Требуем SSL (Heroku этого ожидает)
    return psycopg2.connect(dsn, sslmode="require")

def init_db():
    """
    Создаём таблицы, если их ещё нет.
    Вызывается при старте воркера.
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            channel TEXT NOT NULL,
            content TEXT NOT NULL,
            scheduled_at TIMESTAMPTZ,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            at TIMESTAMPTZ DEFAULT NOW(),
            message TEXT
        );
        """)
        conn.commit()
    print("DB: tables ensured")  # это увидим в Heroku Logs

def add_log(message: str):
    """
    Записывает строку в таблицу logs (для проверки и отладки).
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO logs(message) VALUES (%s)", (message,))
        conn.commit()
