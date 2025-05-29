import os
import io
import json
import re
import smtplib
import logging
import base64
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import redis
import jwt
from flask import Flask, request, jsonify, render_template, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
import httpx
import openai
from twilio.rest import Client as TwilioClient
from mailchimp_marketing import Client as MailchimpClient
from dotenv import load_dotenv
from fpdf import FPDF
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import pytesseract
from io import BytesIO
from fuzzywuzzy import fuzz

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
        host='redis-12345.us-east-1-2.ec2.cloud.redislabs.com',  # Replace with your Redis host
        port=12345,  # Replace with your Redis port
        password='your-redis-password',  # Replace with your Redis password
        decode_responses=True
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

# Environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER', 'your-email@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'your-password')
REALNEX_API_BASE = os.getenv('REALNEX_API_BASE', 'https://sync.realnex.com/api/v1')
TWILIO_SID = os.getenv('TWILIO_SID', 'your-twilio-sid')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', 'your-twilio-auth-token')
TWILIO_PHONE = os.getenv('TWILIO_PHONE', 'your-twilio-phone')
MAILCHIMP_SERVER_PREFIX = os.getenv('MAILCHIMP_SERVER_PREFIX', 'us1')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', 'your-google-api-key')

# Initialize clients with error handling
try:
    openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY', 'your-openai-api-key'))
    logger.info("OpenAI client initialized successfully.")
except Exception as e:
    logger.error(f"OpenAI client initialization failed: {e}")
    openai_client = None

try:
    twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
    logger.info("Twilio client initialized successfully.")
except Exception as e:
    logger.error(f"Twilio client initialization failed: {e}")
    twilio_client = None

mailchimp = None

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

# Helper functions
def log_user_activity(user_id, action, details):
    """Log user activity for auditing and analytics."""
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, action, json.dumps(details), timestamp))
    conn.commit()
    logger.info(f"Logged activity for user {user_id}: {action} - {details}")

def get_user_settings(user_id):
    """Retrieve user settings from the database or return defaults."""
    cursor.execute("SELECT language, subject_generator_enabled, deal_alerts_enabled, email_notifications, sms_notifications FROM user_settings WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        return {
            "language": result[0],
            "subject_generator_enabled": bool(result[1]),
            "deal_alerts_enabled": bool(result[2]),
            "email_notifications": bool(result[3]),
            "sms_notifications": bool(result[4])
        }
    default_settings = {
        "language": "en",
        "subject_generator_enabled": True,
        "deal_alerts_enabled": True,
        "email_notifications": True,
        "sms_notifications": True
    }
    cursor.execute("INSERT INTO user_settings (user_id, language, subject_generator_enabled, deal_alerts_enabled, email_notifications, sms_notifications) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, default_settings["language"], 1, 1, 1, 1))
    conn.commit()
    return default_settings

def get_token(user_id, service):
    """Retrieve a token from Redis or the database, with caching."""
    cache_key = f"token:{user_id}:{service}"
    if redis_client:
        token = redis_client.get(cache_key)
        if token:
            logger.debug(f"Token for {user_id}:{service} retrieved from Redis cache.")
            return token
    cursor.execute("SELECT token FROM user_tokens WHERE user_id = ? AND service = ?", (user_id, service))
    result = cursor.fetchone()
    if result:
        token = result[0]
        if redis_client:
            redis_client.setex(cache_key, 3600, token)
            logger.debug(f"Token for {user_id}:{service} cached in Redis.")
        return token
    logger.warning(f"No token found for {user_id}:{service}.")
    return None

def award_points(user_id, points, reason):
    """Award points to a user and update their email credits and MSA status."""
    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    current_points = user_data[0] if user_data else 0
    email_credits = user_data[1] if user_data else 0
    has_msa = user_data[2] if user_data else 0

    new_points = current_points + points
    points_message = f"Awarded {points} points for {reason}. Total points: {new_points}."

    if new_points >= 1000 and email_credits == 0:
        email_credits = 1000
        points_message += " Congrats! You’ve earned 1000 email credits! 🎉"

    cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, email_credits, has_msa) VALUES (?, ?, ?, ?)",
                   (user_id, new_points, email_credits, has_msa))
    conn.commit()
    log_user_activity(user_id, "award_points", {"points": points, "reason": reason})
    return new_points, email_credits, has_msa, points_message

def update_onboarding(user_id, step):
    """Mark an onboarding step as completed for a user."""
    cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, 1)", (user_id, step))
    conn.commit()
    log_user_activity(user_id, "update_onboarding", {"step": step})

async def get_realnex_data(user_id, endpoint):
    """Fetch data from the RealNex API for a given endpoint."""
    token = get_token(user_id, "realnex")
    if not token:
        logger.error(f"No RealNex token for user {user_id}.")
        return None
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{REALNEX_API_BASE}/{endpoint}", headers={'Authorization': f'Bearer {token}'})
            if response.status_code == 200:
                return response.json()
            logger.error(f"Failed to fetch RealNex data: {response.text}")
            return None
        except Exception as e:
            logger.error(f"RealNex API request failed: {e}")
            return None

def send_2fa_code(user_id):
    """Send a 2FA code to the user via SMS."""
    if not twilio_client:
        logger.error("Twilio client not initialized.")
        return False
    code = str(np.random.randint(100000, 999999))
    expiry = datetime.now() + timedelta(minutes=10)
    cursor.execute("INSERT OR REPLACE INTO two_fa_codes (user_id, code, expiry) VALUES (?, ?, ?)",
                   (user_id, code, expiry.isoformat()))
    conn.commit()

    try:
        twilio_client.messages.create(
            body=f"Your 2FA code is {code}. It expires in 10 minutes.",
            from_=TWILIO_PHONE,
            to="+1234567890"  # Replace with actual user phone number from database
        )
        log_user_activity(user_id, "send_2fa_code", {"code": code})
        return True
    except Exception as e:
        logger.error(f"Failed to send 2FA code: {e}")
        return False

def check_2fa(user_id, code):
    """Verify a 2FA code for a user."""
    cursor.execute("SELECT code, expiry FROM two_fa_codes WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        logger.warning(f"No 2FA code found for user {user_id}.")
        return False
    stored_code, expiry = result
    if datetime.fromisoformat(expiry) < datetime.now():
        logger.warning(f"2FA code expired for user {user_id}.")
        return False
    if stored_code == code:
        log_user_activity(user_id, "check_2fa", {"status": "success"})
        return True
    log_user_activity(user_id, "check_2fa", {"status": "failed"})
    return False

def hash_contact(contact):
    """Generate a hash of a contact's key fields to detect duplicates."""
    key_fields = f"{contact.get('Email', '')}{contact.get('Full Name', '')}{contact.get('Work Phone', '')}"
    return hashlib.sha256(key_fields.encode()).hexdigest()

def log_duplicate(user_id, contact):
    """Log a duplicate contact in the database."""
    contact_hash = hash_contact(contact)
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO duplicates_log (user_id, contact_hash, contact_data, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, contact_hash, json.dumps(contact), timestamp))
    conn.commit()
    log_user_activity(user_id, "log_duplicate", {"contact_hash": contact_hash})

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

def generate_deal_trend_chart(user_id, historical_data, deal_type):
    """Generate a trend chart for deal predictions."""
    plt.figure(figsize=(10, 6))
    sns.set(style="whitegrid")
    
    sq_ft = [item.get("sq_ft", 0) for item in historical_data]
    values = [item.get("rent_month", 0) if deal_type == "LeaseComp" else item.get("sale_price", 0) for item in historical_data]
    
    plt.scatter(sq_ft, values, color='blue', label='Historical Data')
    plt.xlabel('Square Footage')
    plt.ylabel('Rent/Month ($)' if deal_type == "LeaseComp" else 'Sale Price ($)')
    plt.title(f'{deal_type} Trends for User {user_id}')
    plt.legend()
    
    chart_output = BytesIO()
    plt.savefig(chart_output, format='png')
    plt.close()
    chart_output.seek(0)
    return chart_output

# Routes
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

@app.route('/save_token', methods=['POST'])
@token_required
def save_token(user_id):
    """Save an API token for a user and service."""
    data = request.json
    service = data.get('service')
    token = data.get('token')
    
    if not service or not token:
        return jsonify({"error": "Service and token are required"}), 400
    
    cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                   (user_id, service, token))
    conn.commit()
    if redis_client:
        redis_client.setex(f"token:{user_id}:{service}", 3600, token)
    log_user_activity(user_id, "save_token", {"service": service})
    return jsonify({"status": f"Token for {service} saved successfully"})

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

@app.route('/activity_log', methods=['GET'])
@token_required
def get_activity_log(user_id):
    """Retrieve the user's activity log."""
    cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
    logs = cursor.fetchall()
    result = [{"action": log[0], "details": json.loads(log[1]), "timestamp": log[2]} for log in logs]
    return jsonify({"activity_log": result})

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
    log_user_activity(user_id, "save_email_template", {"template_name": template_name})
    return jsonify({"status": "Email template saved successfully"})

@app.route('/get_email_templates', methods=['GET'])
@token_required
def get_email_templates(user_id):
    """Retrieve all email templates for the user."""
    cursor.execute("SELECT template_name, subject, body FROM email_templates WHERE user_id = ?", (user_id,))
    templates = cursor.fetchall()
    result = [{"template_name": t[0], "subject": t[1], "body": t[2]} for t in templates]
    return jsonify({"templates": result})

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
    log_user_activity(user_id, "schedule_task", {"task_type": task_type, "schedule_time": schedule_time})
    return jsonify({"status": "Task scheduled successfully"})

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
    log_user_activity(user_id, "generate_report", {"report_type": report_type})
    
    return send_file(
        pdf_output,
        attachment_filename=f"{report_type}_report_{user_id}.pdf",
        as_attachment=True,
        mimetype='application/pdf'
    )

# Chat Hub Endpoints
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

# Main Dashboard Endpoints
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

@app.route('/market-insights', methods=['GET'])
@token_required
async def market_insights(user_id):
    """Generate AI-powered market insights using OpenAI."""
    if not openai_client:
        return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

    cursor.execute("SELECT amount, close_date FROM deals WHERE user_id = ? ORDER BY close_date DESC LIMIT 5", (user_id,))
    deals = cursor.fetchall()
    deal_context = "Recent Deals:\n"
    for deal in deals:
        deal_context += f"- Amount: ${deal[0]}, Close Date: {deal[1]}\n"

    cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
    activities = cursor.fetchall()
    activity_context = "Recent Activity:\n"
    for activity in activities:
        activity_context += f"- Action: {activity[0]}, Details: {activity[1]}, Timestamp: {activity[2]}\n"

    prompt = (
        f"You are a commercial real estate market analyst. Based on the following data, provide a brief market insight or trend prediction for the user:\n\n"
        f"{deal_context}\n"
        f"{activity_context}\n"
        "Provide a concise insight (2-3 sentences) about the market trends or opportunities the user should be aware of."
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a commercial real estate market analyst."},
                {"role": "user", "content": prompt}
            ]
        )
        insight = response.choices[0].message.content
        log_user_activity(user_id, "generate_market_insight", {"insight": insight})
        return jsonify({"insight": insight})
    except Exception as e:
        logger.error(f"Failed to generate market insight: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Duplicates Dashboard Endpoint
@app.route('/duplicates-data', methods=['GET'])
@token_required
def duplicates_data(user_id):
    """Fetch duplicate contacts based on fuzzy matching from contacts table with caching."""
    cache_key = f"duplicates_data:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    cursor.execute("SELECT id, name, email FROM contacts WHERE user_id = ?", (user_id,))
    contacts = cursor.fetchall()
    duplicates = []
    
    for i, contact in enumerate(contacts):
        for j, other in enumerate(contacts[i+1:], start=i+1):
            name_similarity = fuzz.token_sort_ratio(contact[1], other[1])
            email_similarity = fuzz.token_sort_ratio(contact[2], other[2])
            if name_similarity > 85 or email_similarity > 90:
                duplicates.append({
                    "contact1": {"id": contact[0], "name": contact[1], "email": contact[2]},
                    "contact2": {"id": other[0], "name": other[1], "email": other[2]},
                    "name_similarity": name_similarity,
                    "email_similarity": email_similarity
                })
    
    data = {"duplicates": duplicates}
    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(data))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(data)

# Deal Trends Endpoint
@app.route('/deal-trends-data', methods=['GET'])
@token_required
def deal_trends_data(user_id):
    """Fetch and predict deal trends with caching."""
    cache_key = f"deal_trends_data:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    cursor.execute("SELECT amount, close_date FROM deals WHERE user_id = ? ORDER BY close_date", (user_id,))
    deals = cursor.fetchall()
    
    if not deals:
        data = {"trends": [], "predictions": []}
        if redis_client:
            redis_client.setex(cache_key, 300, json.dumps(data))
        return jsonify(data)
    
    dates = [datetime.strptime(deal[1], '%Y-%m-%d').timestamp() for deal in deals]
    amounts = [deal[0] for deal in deals]
    
    X = np.array(dates).reshape(-1, 1)
    y = np.array(amounts)
    
    model = LinearRegression()
    model.fit(X, y)
    
    last_date = dates[-1]
    future_dates = [last_date + i * 30 * 24 * 60 * 60 for i in range(1, 4)]
    future_X = np.array(future_dates).reshape(-1, 1)
    predictions = model.predict(future_X).tolist()
    
    trends = [{"date": deal[1], "amount": deal[0]} for deal in deals]
    future_predictions = [{"date": datetime.fromtimestamp(fd).strftime('%Y-%m-%d'), "amount": int(pred)} for fd, pred in zip(future_dates, predictions)]
    
    data = {"trends": trends, "predictions": future_predictions}
    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(data))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(data)

# Field Mapping Endpoints
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
    logger.info(f"Saved mapping: {name} - {contacts}")
    return jsonify({"status": "Mapping saved"})

# OCR Endpoint
@app.route('/process-ocr', methods=['POST'])
@token_required
async def process_ocr(user_id):
    """Process an image with OCR, parse text, and auto-sync to RealNex."""
    if 'image' not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    image = request.files['image']
    try:
        img = Image.open(image)
        text = pytesseract.image_to_string(img)

        name_pattern = r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|[A-Z][a-z]+)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        phone_pattern = r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"

        name = re.search(name_pattern, text)
        email = re.search(email_pattern, text)
        phone = re.search(phone_pattern, text)

        contact = {
            "Full Name": name.group(0) if name else "Unknown",
            "Email": email.group(0) if email else "",
            "Work Phone": phone.group(0) if phone else ""
        }

        details = {"filename": image.filename, "extracted_text": text, "parsed_contact": contact}
        timestamp = datetime.now().isoformat()
        cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                       (user_id, "process_ocr", json.dumps(details), timestamp))
        conn.commit()

        token = get_token(user_id, "realnex")
        if token and contact["Email"]:
            contacts = [contact]
            df = pd.DataFrame(contacts)
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REALNEX_API_BASE}/ImportData",
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                    data=csv_data
                )

            if response.status_code == 200:
                cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                               (contact["Email"], contact["Full Name"], contact["Email"], user_id))
                conn.commit()
                log_user_activity(user_id, "auto_sync_ocr_contact", {"contact": contact})
                return jsonify({"text": text, "parsed_contact": contact, "sync_status": "Contact synced to RealNex"})
            else:
                return jsonify({"text": text, "parsed_contact": contact, "sync_status": f"Failed to sync: {response.text}"})
        return jsonify({"text": text, "parsed_contact": contact, "sync_status": "No RealNex token or email found"})
    except Exception as e:
        logger.error(f"OCR processing failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Settings Endpoints
@app.route('/settings-data', methods=['GET'])
@token_required
def get_settings(user_id):
    """Fetch current settings."""
    try:
        with open('settings.json', 'r') as f:
            settings = json.load(f)
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Failed to load settings: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/save-settings', methods=['POST'])
@token_required
def save_settings(user_id):
    """Save updated settings."""
    try:
        settings = request.json
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
        return jsonify({"status": "Settings saved"})
    except Exception as e:
        logger.error(f"Failed to save settings: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/register-webhook', methods=['POST'])
@token_required
async def register_webhook(user_id):
    """Register a webhook URL for the user to receive deal alerts."""
    data = request.json
    webhook_url = data.get('webhook_url')

    if not webhook_url:
        return jsonify({"error": "Webhook URL is required"}), 400

    if not re.match(r'^https?://', webhook_url):
        return jsonify({"error": "Invalid webhook URL format"}), 400

    cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                   (user_id, webhook_url))
    conn.commit()

    log_user_activity(user_id, "register_webhook", {"webhook_url": webhook_url})
    return jsonify({"status": "Webhook registered successfully"})

# Natural language query route
@app.route('/ask', methods=['POST'])
@token_required
async def ask(user_id):
    """Handle natural language queries for CRE tasks."""
    data = request.json
    message = data.get('message', '').lower()

    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    points = user_data[0] if user_data else 0
    email_credits = user_data[1] if user_data else 0
    has_msa = user_data[2] if user_data else 0

    settings = get_user_settings(user_id)
    onboarding_steps = ["save_settings", "sync_crm_data", "send_realblast", "send_training_reminder"]
    completed_steps = []
    for step in onboarding_steps:
        cursor.execute("SELECT completed FROM user_onboarding WHERE user_id = ? AND step = ?", (user_id, step))
        result = cursor.fetchone()
        if result and result[0] == 1:
            completed_steps.append(step)

    # Translate non-English commands to English
    original_message = message
    if settings["language"] != "en":
        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": f"Translate this {settings['language']} text to English."},
                    {"role": "user", "content": message}
                ]
            )
            message = response.choices[0].message.content.lower()
            log_user_activity(user_id, "translate_message", {"from": settings["language"], "to": "en", "original": original_message, "translated": message})
        except Exception as e:
            logger.error(f"Translation failed: {e}")

    # Handle human help requests
    help_phrases = ["i need a human", "more help", "support help", "billing help", "sales support"]
    if any(phrase in message for phrase in help_phrases):
        issue = "General support request"
        to_email = "support@realnex.com"
        if "billing help" in message or "sales support" in message:
            issue = "Billing or sales support request"
            to_email = "sales@realnex.com"

        subject = f"Support Request from User {user_id}"
        body = (
            f"User ID: {user_id}\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Issue: {issue}\n"
            f"Details: {message}\n\n"
            "Please assist this user as soon as possible."
        )
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, to_email, msg.as_string())
            contact_info = (
                "I’ve sent a support request to the RealNex team for you! They’ll get back to you soon. "
                "If you need to reach them directly, here’s their contact info:\n"
                "📞 Phone: (281) 299-3161\n"
                "📧 Email: info@realnex.com (general inquiries), sales@realnex.com (sales/billing), support@realnex.com (support)\n"
                "Hang tight! 🛠️"
            )
            log_user_activity(user_id, "request_support", {"issue": issue, "to_email": to_email})
            return jsonify({"answer": contact_info, "tts": contact_info})
        except Exception as e:
            error_message = f"Failed to send support request: {str(e)}. Please try again or contact RealNex directly at (281) 299-3161 or support@realnex.com."
            return jsonify({"answer": error_message, "tts": error_message})

    # AI-driven commands
    if 'draft an email' in message:
        campaign_type = "RealBlast" if "realblast" in message else "Mailchimp"
        subject = "Your CRE Update"
        audience_id = None
        content = None

        if "realblast" in message:
            answer = "Let’s draft a RealBlast email! What’s the subject? (e.g., 'New Property Listing') Or say 'suggest a subject' to get ideas."
            return jsonify({"answer": answer, "tts": answer})
        else:
            answer = "Let’s draft a Mailchimp email! What’s the subject? (e.g., 'Your CRE Update') Or say 'suggest a subject' to get ideas."
            return jsonify({"answer": answer, "tts": answer})

    elif 'suggest a subject' in message:
        if not settings["subject_generator_enabled"]:
            answer = "Subject line generator is disabled in settings. Enable it to get suggestions! ⚙️"
            return jsonify({"answer": answer, "tts": answer})

        campaign_type = "RealBlast" if "realblast" in message else "Mailchimp"
        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert in email marketing for commercial real estate."},
                    {"role": "user", "content": f"Generate a catchy subject line for a {campaign_type} email campaign."}
                ]
            )
            subject = response.choices[0].message.content.strip()
            answer = f"Suggested subject: '{subject}'. Does this work? Say the subject to use it, or provide your own!"
            log_user_activity(user_id, "suggest_subject", {"campaign_type": campaign_type, "subject": subject})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to generate subject line: {str(e)}. Try providing your own subject."
            return jsonify({"answer": answer, "tts": answer})

    elif 'subject' in message and 'realblast' in message:
        subject = message.split('subject')[-1].strip()
        answer = f"Got the subject: '{subject}'. Which RealNex group ID should this go to? (e.g., 'group123')"
        return jsonify({"answer": answer, "tts": answer})

    elif 'group id' in message:
        audience_id = message.split('group id')[-1].strip()
        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Draft a RealBlast email for group {audience_id} with subject 'Your CRE Update'."}
                ]
            )
            content = response.choices[0].message.content
            answer = f"Here’s your RealBlast email for group {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your RealNex RealBlast setup. 📧"
            log_user_activity(user_id, "draft_email", {"type": "RealBlast", "group_id": audience_id})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to draft email: {str(e)}. Try again."
            return jsonify({"answer": answer, "tts": answer})

    elif 'subject' in message and 'mailchimp' in message:
        subject = message.split('subject')[-1].strip()
        answer = f"Got the subject: '{subject}'. Which Mailchimp audience ID should this go to? (e.g., 'audience456')"
        return jsonify({"answer": answer, "tts": answer})

    elif 'audience id' in message:
        audience_id = message.split('audience id')[-1].strip()
        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Draft a Mailchimp email for audience {audience_id} with subject 'Your CRE Update'."}
                ]
            )
            content = response.choices[0].message.content
            answer = f"Here’s your Mailchimp email for audience {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your Mailchimp campaign setup. 📧"
            log_user_activity(user_id, "draft_email", {"type": "Mailchimp", "audience_id": audience_id})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to draft email: {str(e)}. Try again."
            return jsonify({"answer": answer, "tts": answer})

    elif 'send realblast' in message:
        group_id = None
        campaign_content = None
        if 'group' in message:
            group_id = message.split('group')[-1].strip().split()[0]
        if 'content' in message:
            campaign_content = message.split('content')[-1].strip()

        if not group_id or not campaign_content:
            answer = "To send a RealBlast, I need the group ID and campaign content. Say something like 'send realblast to group group123 with content Check out this property!'. What’s the group ID and content? 📧"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to send a RealBlast. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        if not twilio_client:
            return jsonify({"error": "Twilio client not initialized. Check server logs for details."}), 500

        two_fa_code = data.get('two_fa_code')
        if not two_fa_code:
            if not send_2fa_code(user_id):
                return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
            answer = "2FA code sent to your phone. Please provide the code to proceed with sending the RealBlast. 🔒"
            return jsonify({"answer": answer, "tts": answer})

        if not check_2fa(user_id, two_fa_code):
            answer = "Invalid 2FA code. Try again."
            return jsonify({"answer": answer, "tts": answer})

        if has_msa:
            cursor.execute("UPDATE user_points SET has_msa = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            socketio.emit('msa_update', {'user_id': user_id, 'message': "Used your free RealBlast MSA! Nice work! 🚀"})
        elif email_credits > 0:
            email_credits -= 1
            cursor.execute("UPDATE user_points SET email_credits = ? WHERE user_id = ?", (email_credits, user_id))
            conn.commit()
            socketio.emit('credits_update', {'user_id': user_id, 'email_credits': email_credits, 'message': f"Used 1 email credit for RealBlast. You have {email_credits} credits left. 📧"})
        else:
            answer = "You need email credits or a free RealBlast MSA to send a RealBlast! Earn 1000 points to unlock 1000 credits, or complete onboarding for a free MSA. Check your status with 'my status'. 🚀"
            return jsonify({"answer": answer, "tts": answer})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{REALNEX_API_BASE}/RealBlasts",
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json={"group_id": group_id, "content": campaign_content}
            )

        if response.status_code == 200:
            points, email_credits, has_msa, points_message = award_points(user_id, 15, "sending a RealNex RealBlast")
            socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"RealBlast sent to group {group_id}!"})
            update_onboarding(user_id, "send_realblast")
            answer = f"RealBlast sent to group {group_id}! 📧 {points_message}"
            if settings["sms_notifications"] and twilio_client:
                twilio_client.messages.create(
                    body=f"RealBlast sent to group {group_id}! {points_message}",
                    from_=TWILIO_PHONE,
                    to="+1234567890"
                )
            log_user_activity(user_id, "send_realblast", {"group_id": group_id})
            return jsonify({"answer": answer, "tts": answer})
        answer = f"Failed to send RealBlast: {response.text}"
        return jsonify({"answer": answer, "tts": answer})

    elif 'send mailchimp campaign' in message:
        audience_id = None
        campaign_content = None
        if 'audience' in message:
            audience_id = message.split('audience')[-1].strip().split()[0]
        if 'content' in message:
            campaign_content = message.split('content')[-1].strip()

        if not audience_id or not campaign_content:
            answer = "To send a Mailchimp campaign, I need the audience ID and campaign content. Say something like 'send mailchimp campaign to audience audience456 with content Check out this property!'. What’s the audience ID and content? 📧"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "mailchimp")
        if not token:
            answer = "Please add your Mailchimp API key in Settings to send a Mailchimp campaign. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        global mailchimp
        mailchimp = MailchimpClient()
        mailchimp.set_config({"api_key": token, "server": MAILCHIMP_SERVER_PREFIX})

        if not twilio_client:
            return jsonify({"error": "Twilio client not initialized. Check server logs for details."}), 500

        two_fa_code = data.get('two_fa_code')
        if not two_fa_code:
            if not send_2fa_code(user_id):
                return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
            answer = "2FA code sent to your phone. Please provide the code to proceed with sending the Mailchimp campaign. 🔒"
            return jsonify({"answer": answer, "tts": answer})

        if not check_2fa(user_id, two_fa_code):
            answer = "Invalid 2FA code. Try again."
            return jsonify({"answer": answer, "tts": answer})

        try:
            campaign = mailchimp.campaigns.create({
                "type": "regular",
                "recipients": {"list_id": audience_id},
                "settings": {
                    "subject_line": "Your CRE Campaign",
                    "from_name": "Matty’s Maverick & Goose",
                    "reply_to": "noreply@example.com"
                }
            })
            campaign_id = campaign.get("id")
            mailchimp.campaigns.set_content(campaign_id, {"html": campaign_content})
            mailchimp.campaigns.actions.send(campaign_id)
            socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"Mailchimp campaign sent to audience {audience_id}!"})
            answer = f"Mailchimp campaign sent to audience {audience_id}! 📧"
            if settings["email_notifications"]:
                msg = MIMEText(f"Mailchimp campaign sent to audience {audience_id}!")
                msg['Subject'] = "Campaign Sent Notification"
                msg['From'] = SMTP_USER
                msg['To'] = "user@example.com"
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(SMTP_USER, "user@example.com", msg.as_string())
            log_user_activity(user_id, "send_mailchimp_campaign", {"audience_id": audience_id})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to send Mailchimp campaign: {str(e)}"
            return jsonify({"answer": answer, "tts": answer})

    elif 'sync crm data' in message:
        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to sync CRM data. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        zoominfo_token = get_token(user_id, "zoominfo")
        apollo_token = get_token(user_id, "apollo")

        zoominfo_contacts = []
        if zoominfo_token:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.zoominfo.com/v1/contacts",
                    headers={"Authorization": f"Bearer {zoominfo_token}"}
                )
            if response.status_code == 200:
                zoominfo_contacts = response.json().get("contacts", [])
            else:
                answer = f"Failed to fetch ZoomInfo contacts: {response.text}. Check your ZoomInfo token in Settings."
                return jsonify({"answer": answer, "tts": answer})

        apollo_contacts = []
        if apollo_token:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.apollo.io/v1/contacts",
                    headers={"Authorization": f"Bearer {apollo_token}"}
                )
            if response.status_code == 200:
                apollo_contacts = response.json().get("contacts", [])
            else:
                answer = f"Failed to fetch Apollo.io contacts: {response.text}. Check your Apollo.io token in Settings."
                return jsonify({"answer": answer, "tts": answer})

        contacts = []
        seen_hashes = set()
        for contact in zoominfo_contacts + apollo_contacts:
            contact_hash = hash_contact(contact)
            if contact_hash in seen_hashes:
                log_duplicate(user_id, contact)
                continue
            seen_hashes.add(contact_hash)
            formatted_contact = {
                "Full Name": contact.get("name", ""),
                "First Name": contact.get("first_name", ""),
                "Last Name": contact.get("last_name", ""),
                "Company": contact.get("company", ""),
                "Address1": contact.get("address", ""),
                "City": contact.get("city", ""),
                "State": contact.get("state", ""),
                "Postal Code": contact.get("zip", ""),
                "Work Phone": contact.get("phone", ""),
                "Email": contact.get("email", "")
            }
            contacts.append(formatted_contact)

        if contacts:
            df = pd.DataFrame(contacts)
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REALNEX_API_BASE}/ImportData",
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                    data=csv_data
                )

            if response.status_code == 200:
                points, email_credits, has_msa, points_message = award_points(user_id, 10, "bringing in data")
                update_onboarding(user_id, "sync_crm_data")
                for contact in contacts:
                    cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                   (contact["Email"], contact["Full Name"], contact["Email"], user_id))
                conn.commit()
                answer = f"Synced {len(contacts)} contacts into RealNex. 📇 {points_message}"
                log_user_activity(user_id, "sync_crm_data", {"num_contacts": len(contacts)})
                return jsonify({"answer": answer, "tts": answer})
            answer = f"Failed to import contacts into RealNex: {response.text}"
            return jsonify({"answer": answer, "tts": answer})
        answer = "No contacts to sync."
        return jsonify({"answer": answer, "tts": answer})

    elif 'predict deal' in message:
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
        sq_ft = None
        if 'square footage' in message or 'sq ft' in message:
            sq_ft = re.search(r'\d+', message)
            sq_ft = int(sq_ft.group()) if sq_ft else None

        if not deal_type or not sq_ft:
            answer = "To predict a deal, I need the deal type (LeaseComp or SaleComp) and square footage. Say something like 'predict deal for LeaseComp with 5000 sq ft'. What’s the deal type and square footage? 🔮"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to predict a deal. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        historical_data = await get_realnex_data(user_id, f"{deal_type}s")
        if not historical_data:
            answer = "No historical data available for prediction."
            return jsonify({"answer": answer, "tts": answer})

        X = []
        y = []
        prediction = 0
        if deal_type == "LeaseComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("rent_month", 0))
            model = LinearRegression()
            model.fit(X, y)
            prediction = model.predict([[sq_ft]])[0]
            answer = f"Predicted rent for {sq_ft} sq ft: ${prediction:.2f}/month. 🔮"
            chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type)
            chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
            answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
            cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                           (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
            conn.commit()
            log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction})
            tts = f"Predicted rent for {sq_ft} square feet: ${prediction:.2f} per month."
        elif deal_type == "SaleComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("sale_price", 0))
            model = LinearRegression()
            model.fit(X, y)
            prediction = model.predict([[sq_ft]])[0]
            answer = f"Predicted sale price for {sq_ft} sq ft: ${prediction:.2f}. 🔮"
            chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type)
            chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
            answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
            cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                           (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
            conn.commit()
            log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction})
            tts = f"Predicted sale price for {sq_ft} square feet: ${prediction:.2f}."

        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        alert = cursor.fetchone()
        if alert:
            threshold, alert_deal_type = alert
            if (alert_deal_type == "Any" or alert_deal_type == deal_type) and prediction > threshold:
                cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
                webhook = cursor.fetchone()
                if webhook:
                    webhook_url = webhook[0]
                    alert_data = {
                        "user_id": user_id,
                        "deal_type": deal_type,
                        "prediction": prediction,
                        "threshold": threshold,
                        "message": f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}."
                    }
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(webhook_url, json=alert_data)
                            log_user_activity(user_id, "trigger_webhook", {"webhook_url": webhook_url, "data": alert_data})
                        except Exception as e:
                            logger.error(f"Failed to trigger webhook: {str(e)}")
                if settings["sms_notifications"] and twilio_client:
                    twilio_client.messages.create(
                        body=f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.",
                        from_=TWILIO_PHONE,
                        to="+1234567890"  # Replace with user phone from users table
                    )
                if settings["email_notifications"]:
                    msg = MIMEText(f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.")
                    msg['Subject'] = "Deal Alert Notification"
                    msg['From'] = SMTP_USER
                    msg['To'] = "user@example.com"  # Replace with user email from users table
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SMTP_USER, SMTP_PASSWORD)
                        server.sendmail(SMTP_USER, "user@example.com", msg.as_string())

        return jsonify({"answer": answer, "tts": tts})

    elif 'negotiate deal' in message:
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
        sq_ft = None
        offered_value = None
        if 'square footage' in message or 'sq ft' in message:
            sq_ft = re.search(r'square footage\s*(\d+)|sq ft\s*(\d+)', message)
            sq_ft = int(sq_ft.group(1) or sq_ft.group(2)) if sq_ft else None
        if 'offered' in message:
            offered_value = re.search(r'offered\s*\$\s*([\d.]+)', message)
            offered_value = float(offered_value.group(1)) if offered_value else None

        if not deal_type or not sq_ft or not offered_value:
            answer = "To negotiate a deal, I need the deal type (LeaseComp or SaleComp), square footage, and offered value. Say something like 'negotiate deal for LeaseComp with 5000 sq ft offered $5000'. What’s the deal type, square footage, and offered value? 🤝"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to negotiate a deal. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

        historical_data = await get_realnex_data(user_id, f"{deal_type}s")
        if not historical_data:
            answer = "No historical data available for negotiation."
            return jsonify({"answer": answer, "tts": answer})

        prompt = (
            f"You are a commercial real estate negotiation expert. Based on the following historical {deal_type} data, "
            f"suggest a counteroffer for a property with {sq_ft} square feet, where the offered value is ${offered_value} "
            f"({'per month' if deal_type == 'LeaseComp' else 'total'}). Historical data (square footage, value):\n"
        )
        for item in historical_data:
            sq_ft_value = item.get("sq_ft", 0)
            value = item.get("rent_month", 0) if deal_type == "LeaseComp" else item.get("sale_price", 0)
            prompt += f"- {sq_ft_value} sq ft: ${value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
        prompt += "Provide a counteroffer with a confidence score (0-100) and a brief explanation."

        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a commercial real estate negotiation expert."},
                    {"role": "user", "content": prompt}
                ]
            )
            ai_response = response.choices[0].message.content

            counteroffer_match = re.search(r'Counteroffer: \$([\d.]+)', ai_response)
            confidence_match = re.search(r'Confidence: (\d+)%', ai_response)
            explanation_match = re.search(r'Explanation: (.*?)(?:\n|$)', ai_response)

            counteroffer = float(counteroffer_match.group(1)) if counteroffer_match else offered_value * 1.1
            confidence = int(confidence_match.group(1)) if confidence_match else 75
            explanation = explanation_match.group(1) if explanation_match else "Based on historical data trends."

            answer = (
                f"Negotiation Suggestion for {deal_type}:\n"
                f"Offered: ${offered_value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                f"Counteroffer: ${round(counteroffer, 2)} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                f"Confidence: {confidence}%\n"
                f"Explanation: {explanation}\n"
                f"Ready to close this deal? 🤝"
            )
            log_user_activity(user_id, "negotiate_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "offered_value": offered_value, "counteroffer": counteroffer})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to negotiate deal: {str(e)}. Try again."
            return jsonify({"answer": answer, "tts": answer})

    elif 'notify me of new deals over' in message:
        if not settings["deal_alerts_enabled"]:
            answer = "Deal alerts are disabled in settings. Enable them to set notifications! ⚙️"
            return jsonify({"answer": answer, "tts": answer})
        else:
            threshold = re.search(r'over\s*\$\s*([\d.]+)', message)
            threshold = float(threshold.group(1)) if threshold else None
            deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else "Any"
            if not threshold:
                answer = "Please specify a deal value threshold, like 'notify me of new deals over $5000'. What’s the threshold? 🔔"
                return jsonify({"answer": answer, "tts": answer})
            else:
                cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold, deal_type) VALUES (?, ?, ?)",
                               (user_id, threshold, deal_type))
                conn.commit()
                answer = f"Deal alert set! I’ll notify you of new {deal_type} deals over ${threshold}. 🔔"
                log_user_activity(user_id, "set_deal_alert", {"threshold": threshold, "deal_type": deal_type})
                return jsonify({"answer": answer, "tts": answer})

    elif 'summarize text' in message:
        text = message.split('summarize text')[-1].strip()
        if not text:
            answer = "Please provide the text to summarize. Say something like 'summarize text This is my text to summarize'. What’s the text? 📝"
            return jsonify({"answer": answer, "tts": answer})

        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a text summarizer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Summarize this text: {text}"}
                ]
            )
            summary = response.choices[0].message.content
            answer = f"Summary: {summary}. 📝"
            log_user_activity(user_id, "summarize_text", {"original_length": len(text), "summary_length": len(summary)})
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to summarize text: {str(e)}. Try again."
            return jsonify({"answer": answer, "tts": answer})

    elif 'verify emails' in message:
        emails = message.split('verify emails')[-1].strip().split(',')
        emails = [email.strip() for email in emails if email.strip()]
        if not emails:
            answer = "Please provide emails to verify. Say something like 'verify emails email1@example.com, email2@example.com'. What are the emails? 📧"
            return jsonify({"answer": answer, "tts": answer})

        verified_emails = []
        for email in emails:
            # Placeholder for email verification logic (e.g., using an external API)
            status = "valid"  # Simplified for demo
            verified_emails.append({"email": email, "status": status})
        answer = f"Verified {len(verified_emails)} emails: {json.dumps(verified_emails)}. ✨"
        log_user_activity(user_id, "verify_emails", {"num_emails": len(emails)})
        return jsonify({"answer": answer, "tts": answer})

    elif 'sync contacts' in message:
        google_token = data.get('google_token')
        if not google_token:
            answer = "I need a Google token to sync contacts. Say something like 'sync contacts with google token your_token_here'. What’s your Google token?"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to sync contacts. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        # Fetch Google contacts
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://www.googleapis.com/contacts/v3/users/me/connections",
                headers={"Authorization": f"Bearer {google_token}"}
            )
        if response.status_code != 200:
            answer = f
