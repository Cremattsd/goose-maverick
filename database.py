import sqlite3

def init_db():
    """Initialize SQLite database and create tables."""
    conn = sqlite3.connect('chatbot.db', check_same_thread=False)
    cursor = conn.cursor()

    # Create tables
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_points
                      (user_id TEXT PRIMARY KEY, points INTEGER, email_credits INTEGER, has_msa INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings
                      (user_id TEXT PRIMARY KEY, language TEXT, subject_generator_enabled INTEGER,
                       deal_alerts_enabled INTEGER, email_notifications INTEGER, sms_notifications INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_tokens
                      (user_id TEXT, service TEXT, token TEXT, PRIMARY KEY (user_id, service))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_onboarding
                      (user_id TEXT, step TEXT, completed INTEGER, PRIMARY KEY (user_id, step))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS deal_alerts
                      (user_id TEXT PRIMARY KEY, threshold REAL, deal_type TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS two_fa_codes
                      (user_id TEXT PRIMARY KEY, code TEXT, expiry TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS duplicates_log
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, contact_hash TEXT,
                       contact_data TEXT, timestamp TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_activity_log
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT,
                       details TEXT, timestamp TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS email_templates
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, template_name TEXT,
                       subject TEXT, body TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS scheduled_tasks
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, task_type TEXT,
                       task_data TEXT, schedule_time TIMESTAMP, status TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT,
                      sender TEXT,
                      message TEXT,
                      timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS contacts
                     (id TEXT,
                      name TEXT,
                      email TEXT,
                      user_id TEXT,
                      PRIMARY KEY (id, user_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS deals
                     (id TEXT,
                      amount INTEGER,
                      close_date TEXT,
                      user_id TEXT,
                      PRIMARY KEY (id, user_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS webhooks
                     (user_id TEXT,
                      webhook_url TEXT,
                      PRIMARY KEY (user_id))''')
    conn.commit()
    return conn, cursor

# Initialize database
conn, cursor = init_db()
