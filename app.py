import os
import json
import logging
import redis
import jwt
from flask import Flask, request, jsonify, render_template, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fpdf import FPDF
from io import BytesIO
import commands  # Import the commands module for the /ask route

# Configure logging for better debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("chatbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Redis setup for caching
try:
    redis_client = redis.Redis(
        host='redis-11362.c265.us-east-1-2.ec2.redns.redis-cloud.com',
        port=11362,
        username=os.getenv('REDIS_USERNAME', 'default'),
        password=os.getenv('REDIS_PASSWORD', ''),
        decode_responses=True,
        ssl=True,
        ssl_ca_certs='certs/redis_ca.pem'
    )
    redis_client.ping()
    logger.info("Redis connection established successfully.")
except redis.ConnectionError as e:
    logger.error(f"Redis connection failed: {e}. Ensure Redis is running.")
    redis_client = None

# Database setup with SQLite
conn = sqlite3.connect('chatbot.db', check_same_thread=False)
cursor = conn.cursor()

# Create tables for user data, settings, tokens, onboarding, alerts, 2FA, duplicates, and more
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

# JWT Token Required Decorator
def token_required(f):
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"error": "Token is missing"}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            kwargs['user_id'] = data.get('user_id', 'default')
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# Helper function for PDF reports
def generate_pdf_report(user_id, data, report_title):
    """Generate a PDF report from given data."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=report_title, ln=True, align='C')
    pdf.ln(10)

    for key, value in data.items():
        pdf.cell(200, 10, txt=f"{key}: {value}", ln=True)
    
    pdf_output = BytesIO()
    pdf.output(pdf_output, 'F')
    pdf_output.seek(0)
    return pdf_output

# Routes for web interface
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Render to detect the app."""
    return jsonify({"status": "healthy"})

@app.route('/', methods=['GET'])
@token_required
def index(user_id):
    logger.info("Main dashboard page accessed.")
    return render_template('main_dashboard.html')

@app.route('/chat-hub', methods=['GET'])
@token_required
def chat_hub(user_id):
    logger.info("Chat hub page accessed.")
    return render_template('index.html')

@app.route('/dashboard', methods=['GET'])
@token_required
def dashboard(user_id):
    logger.info("Duplicates dashboard page accessed.")
    return render_template('duplicates_dashboard.html')

@app.route('/activity', methods=['GET'])
@token_required
def activity(user_id):
    logger.info("Activity log page accessed.")
    return render_template('activity.html')

@app.route('/deal-trends', methods=['GET'])
@token_required
def deal_trends(user_id):
    logger.info("Deal trends page accessed.")
    return render_template('deal_trends.html')

@app.route('/field-map', methods=['GET'])
@token_required
def field_map(user_id):
    logger.info("Field mapping editor page accessed.")
    return render_template('field_map.html')

@app.route('/ocr', methods=['GET'])
@token_required
def ocr_page(user_id):
    logger.info("OCR scanner page accessed.")
    return render_template('ocr.html')

@app.route('/settings', methods=['GET'])
@token_required
def settings_page(user_id):
    logger.info("Settings page accessed.")
    return render_template('settings.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login and issue JWT token."""
    if request.method == 'GET':
        return render_template('login.html')

    data = request.json
    username = data.get('username')
    password = data.get('password')

    # For demo, use a hardcoded user (replace with database lookup in production)
    if username == 'admin' and password == 'password123':
        user_id = 'default'  # Replace with actual user ID from database
        token = jwt.encode({
            'user_id': user_id,
            'user': username,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({"token": token})
    return jsonify({"error": "Invalid credentials"}), 401

# API endpoints for dashboard data
@app.route('/dashboard-data', methods=['GET'])
@token_required
def dashboard_data(user_id):
    """Fetch data for the main dashboard (lead scores) with caching."""
    cache_key = f"dashboard_data:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    lead_scores = [
        {"contact_id": "contact1", "score": 85},
        {"contact_id": "contact2", "score": 92}
    ]
    data = {"lead_scores": lead_scores}

    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(data))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(data)

@app.route('/import-stats', methods=['GET'])
@token_required
def import_stats(user_id):
    """Fetch import statistics with caching."""
    cache_key = f"import_stats:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    stats = {
        "total_imports": 150,
        "successful_imports": 140,
        "duplicates_detected": 10
    }

    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(stats))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(stats)

@app.route('/mission-summary', methods=['GET'])
@token_required
def mission_summary(user_id):
    """Fetch a mission summary with caching."""
    cache_key = f"mission_summary:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    summary = {"summary": "Mission Summary: Synced 150 contacts, detected 10 duplicates, predicted 2 deals."}

    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(summary))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(summary)

# Chat hub endpoints
@app.route('/save-message', methods=['POST'])
@token_required
def save_message(user_id):
    """Save a chat message to the database."""
    data = request.json
    sender = data.get('sender')
    message = data.get('message')
    timestamp = datetime.now().isoformat()
    
    cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, sender, message, timestamp))
    conn.commit()
    return jsonify({"status": "Message saved"})

@app.route('/get-messages', methods=['GET'])
@token_required
def get_messages(user_id):
    """Retrieve chat messages for the user."""
    cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp",
                   (user_id,))
    messages = cursor.fetchall()
    result = [{"sender": msg[0], "message": msg[1], "timestamp": msg[2]} for msg in messages]
    return jsonify({"messages": result})

# Activity log endpoint
@app.route('/activity_log', methods=['GET'])
@token_required
def get_activity_log(user_id):
    """Retrieve the user's activity log."""
    cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
    logs = cursor.fetchall()
    result = [{"action": log[0], "details": json.loads(log[1]), "timestamp": log[2]} for log in logs]
    return jsonify({"activity_log": result})

# Duplicates endpoint
@app.route('/duplicates', methods=['GET'])
@token_required
def get_duplicates(user_id):
    """Retrieve duplicate contacts for the user."""
    cursor.execute("SELECT contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    duplicates = cursor.fetchall()
    result = []
    for dup in duplicates:
        result.append({
            "contact_hash": dup[0],
            "contact_data": json.loads(dup[1]),
            "timestamp": dup[2]
        })
    return jsonify({"duplicates": result})

# Email template endpoints
@app.route('/save_email_template', methods=['POST'])
@token_required
def save_email_template(user_id):
    """Save a custom email template for the user."""
    data = request.json
    template_name = data.get('template_name')
    subject = data.get('subject')
    body = data.get('body')
    
    if not all([template_name, subject, body]):
        return jsonify({"error": "Template name, subject, and body are required"}), 400
    
    cursor.execute("INSERT INTO email_templates (user_id, template_name, subject, body) VALUES (?, ?, ?, ?)",
                   (user_id, template_name, subject, body))
    conn.commit()
    logger.info(f"User {user_id} saved email template: {template_name}")
    return jsonify({"status": "Email template saved successfully"})

@app.route('/get_email_templates', methods=['GET'])
@token_required
def get_email_templates(user_id):
    """Retrieve all email templates for the user."""
    cursor.execute("SELECT template_name, subject, body FROM email_templates WHERE user_id = ?", (user_id,))
    templates = cursor.fetchall()
    result = [{"template_name": t[0], "subject": t[1], "body": t[2]} for t in templates]
    return jsonify({"templates": result})

# Task scheduling endpoint
@app.route('/schedule_task', methods=['POST'])
@token_required
def schedule_task(user_id):
    """Schedule a task like sending a RealBlast or generating a report."""
    data = request.json
    task_type = data.get('task_type')
    task_data = data.get('task_data')
    schedule_time = data.get('schedule_time')  # ISO format
    
    if not all([task_type, task_data, schedule_time]):
        return jsonify({"error": "Task type, data, and schedule time are required"}), 400
    
    cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                   (user_id, task_type, json.dumps(task_data), schedule_time, "pending"))
    conn.commit()
    logger.info(f"User {user_id} scheduled task: {task_type} at {schedule_time}")
    return jsonify({"status": "Task scheduled successfully"})

# Report generation endpoint
@app.route('/generate_report', methods=['POST'])
@token_required
def generate_report(user_id):
    """Generate a PDF report based on user data."""
    data = request.json
    report_type = data.get('report_type', 'activity')
    
    if report_type == 'activity':
        cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
        logs = cursor.fetchall()
        report_data = {}
        for i, log in enumerate(logs, 1):
            report_data[f"Activity {i}"] = f"{log[0]} at {log[2]}: {json.loads(log[1])}"
        title = "Recent Activity Report"
    
    pdf_output = generate_pdf_report(user_id, report_data, title)
    logger.info(f"User {user_id} generated report: {report_type}")
    return send_file(
        pdf_output,
        attachment_filename=f"{report_type}_report_{user_id}.pdf",
        as_attachment=True,
        mimetype='application/pdf'
    )

# Settings endpoints
@app.route('/settings-data', methods=['GET'])
@token_required
def get_settings(user_id):
    """Fetch current settings."""
    try:
        with open('settings.json', 'r') as f:
            settings = json.load(f)
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Failed to load settings for user {user_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/save-settings', methods=['POST'])
@token_required
def save_settings(user_id):
    """Save updated settings."""
    try:
        settings = request.json
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
        logger.info(f"User {user_id} saved settings")
        return jsonify({"status": "Settings saved"})
    except Exception as e:
        logger.error(f"Failed to save settings for user {user_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Field mapping endpoints
@app.route('/field-map/saved/<name>', methods=['GET'])
@token_required
def load_field_mapping(user_id, name):
    """Load a saved field mapping."""
    mappings = {"contacts": {"Full Name": "name", "Email": "email"}}
    return jsonify(mappings.get(name, {"contacts": {}}))

@app.route('/field-map/save/<name>', methods=['POST'])
@token_required
def save_field_mapping(user_id, name):
    """Save a field mapping."""
    data = request.json
    contacts = data.get('contacts', {})
    logger.info(f"User {user_id} saved mapping: {name} - {contacts}")
    return jsonify({"status": "Mapping saved"})

# Register the /ask route from commands.py
commands.register_commands(app, socketio)

# Run the app
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000)
