
import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

# Secure and flexible DB path
base_path = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(base_path / "chatbot.db"))

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id TEXT,
                name TEXT,
                email TEXT,
                phone TEXT,
                user_id TEXT,
                PRIMARY KEY (id, user_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT,
                amount INTEGER,
                close_date TEXT,
                user_id TEXT,
                sq_ft INTEGER,
                rent_month INTEGER,
                sale_price INTEGER,
                deal_type TEXT,
                PRIMARY KEY (id, user_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                sender TEXT,
                message TEXT,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
