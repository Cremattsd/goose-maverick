
from db_service import get_db, init_db

def test_db_init_and_user_insert():
    init_db()
    user_id = "test-user-123"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, datetime('now'))",
                       (user_id, "test@example.com"))
        cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        assert result is not None
        assert result[0] == "test@example.com"
