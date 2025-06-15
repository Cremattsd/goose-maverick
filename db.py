import os
import logging
import sqlite3

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("chatbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database setup with Render Disk path
import os
from pathlib import Path

# Secure DB path
base_path = Path(__file__).parent
db_path = os.getenv('DB_PATH', str(base_path / 'chatbot.db'))
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

# Create tables (combined schema)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT,
        created_at TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS contacts (
        id TEXT,
        name TEXT,
        email TEXT,
        phone TEXT,
        user_id TEXT,
        PRIMARY KEY (id, user_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
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
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        sender TEXT,
        message TEXT,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS duplicates_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        contact_hash TEXT,
        contact_data TEXT,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        action TEXT,
        details TEXT,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_tokens (
        user_id TEXT,
        service TEXT,
        token TEXT,
        PRIMARY KEY (user_id, service),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')

# Updated user_settings table with API key columns
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'")
if cursor.fetchone():
    cursor.execute("PRAGMA table_info(user_settings)")
    columns = {row[1] for row in cursor.fetchall()}
    if 'mailchimp_api_key' not in columns:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN mailchimp_api_key TEXT")
    if 'realnex_api_key' not in columns:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN realnex_api_key TEXT")
else:
    cursor.execute('''
        CREATE TABLE user_settings (
            user_id TEXT PRIMARY KEY,
            language TEXT,
            subject_generator_enabled INTEGER,
            deal_alerts_enabled INTEGER,
            email_notifications INTEGER,
            sms_notifications INTEGER,
            mailchimp_group_id TEXT,
            mailchimp_api_key TEXT,
            constant_contact_group_id TEXT,
            realnex_group_id TEXT,
            realnex_api_key TEXT,
            apollo_group_id TEXT,
            seamless_group_id TEXT,
            zoominfo_group_id TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_points (
        user_id TEXT PRIMARY KEY,
        points INTEGER,
        email_credits INTEGER,
        has_msa INTEGER,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_onboarding (
        user_id TEXT,
        step TEXT,
        completed INTEGER,
        PRIMARY KEY (user_id, step),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS deal_alerts (
        user_id TEXT,
        threshold REAL,
        deal_type TEXT,
        PRIMARY KEY (user_id, deal_type),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS two_fa_codes (
        user_id TEXT PRIMARY KEY,
        code TEXT,
        expiry TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS webhooks (
        user_id TEXT PRIMARY KEY,
        webhook_url TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS health_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        contact_id TEXT,
        email_health_score INTEGER,
        phone_health_score INTEGER,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS email_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        template_name TEXT,
        subject TEXT,
        body TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        task_type TEXT,
        task_data TEXT,
        schedule_time TEXT,
        status TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
''')
conn.commit()


# --- Email Credentials Model (Scaffolded) ---
email_credentials = []  # Replace with DB in production

def save_email_credentials(user_id, provider, token_data):
    email_credentials.append({
        "user_id": user_id,
        "provider": provider,
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": token_data.get("expires_at"),
    })
