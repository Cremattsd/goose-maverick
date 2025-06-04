import os
import logging
import sqlite3
from flask import Flask, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
from datetime import datetime
from config import *

# Import Blueprints
from blueprints.auth import auth_bp
from blueprints.chat import chat_bp
from blueprints.contacts import contacts_bp
from blueprints.deals import deals_bp
from blueprints.user import user_bp
from blueprints.tasks import tasks_bp
from blueprints.templates import templates_bp
from blueprints.reports import reports_bp
from blueprints.webhooks import webhooks_bp

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

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# Database setup
conn = sqlite3.connect('chatbot.db', check_same_thread=False)
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
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id TEXT PRIMARY KEY,
        language TEXT,
        subject_generator_enabled INTEGER,
        deal_alerts_enabled INTEGER,
        email_notifications INTEGER,
        sms_notifications INTEGER,
        mailchimp_group_id TEXT,
        constant_contact_group_id TEXT,
        realnex_group_id TEXT,
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

# Ensure uploads directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Register Blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(chat_bp, url_prefix='/chat')
app.register_blueprint(contacts_bp, url_prefix='/contacts')
app.register_blueprint(deals_bp, url_prefix='/deals')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(tasks_bp, url_prefix='/tasks')
app.register_blueprint(templates_bp, url_prefix='/templates')
app.register_blueprint(reports_bp, url_prefix='/reports')
app.register_blueprint(webhooks_bp, url_prefix='/webhooks')

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "Healthy—ready to close some CRE deals! 🏢"}), 200

# Run the app
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
