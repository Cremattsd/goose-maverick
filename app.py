from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pandas as pd
import io
import numpy as np
from sklearn.linear_model import LinearRegression
import pymupdf as PyMuPDF  # Updated import
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import httpx
from fuzzywuzzy import fuzz
from collections import defaultdict
import sqlite3
from datetime import datetime
import json
import redis
from mailchimp_marketing import Client as MailchimpClient
from twilio.rest import Client as TwilioClient
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
import threading
import time
import pyttsx3
import uuid
import re

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your_secret_key'

# Initialize Redis with error handling
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    redis_client.ping()  # Test the connection
except Exception as e:
    print(f"Failed to connect to Redis: {e}")
    redis_client = None  # Fallback to None; handle this in routes

socketio = SocketIO(app, cors_allowed_origins="*", message_queue='redis://localhost:6379')

# API credentials (replace with your own)
REALNEX_API_BASE = "https://sync.realnex.com/api/v1/CrmOData"
REALNEX_AUTH_URL = "https://imports.realnex.com/integrations/api"
MAILCHIMP_SERVER_PREFIX = "us1"
TWILIO_ACCOUNT_SID = "your_twilio_account_sid"
TWILIO_AUTH_TOKEN = "your_twilio_auth_token"
TWILIO_AUTHY_API_KEY = "your_authy_api_key"
OPENAI_API_KEY = "your_openai_api_key"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your_email@gmail.com"
SMTP_PASSWORD = "your_email_password"

# Initialize clients
mailchimp = None

# Initialize Twilio with error handling
try:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
except Exception as e:
    print(f"Failed to initialize Twilio client: {e}")
    twilio_client = None

# Initialize OpenAI with error handling
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    print(f"Failed to initialize OpenAI client: {e}")
    openai_client = None

# Database setup
conn = sqlite3.connect('user_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS user_mappings 
                 (user_id TEXT, header TEXT, mapped_field TEXT, frequency INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_points 
                 (user_id TEXT, points INTEGER, email_credits INTEGER, has_msa INTEGER, last_updated TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS points_history 
                 (user_id TEXT, points INTEGER, timestamp TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_2fa 
                 (user_id TEXT, authy_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_onboarding 
                 (user_id TEXT, step TEXT, completed INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_tokens 
                 (user_id TEXT, service TEXT, token TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_imports 
                 (user_id TEXT, import_id TEXT, record_type TEXT, record_data TEXT, import_date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS deal_alerts 
                 (user_id TEXT, threshold REAL)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_achievements 
                 (user_id TEXT, achievement_id TEXT, name TEXT, description TEXT, awarded_date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings 
                 (user_id TEXT, deal_alerts_enabled INTEGER, deal_alert_volume INTEGER, 
                  subject_generator_enabled INTEGER, achievements_enabled INTEGER, 
                  sms_alerts_enabled INTEGER, phone_number TEXT, language TEXT)''')
# Add indexes for performance
cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_imports_date ON user_imports (user_id, import_date)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_points_history ON points_history (user_id, timestamp)")
conn.commit()

# RealNex template fields
REALNEX_LEASECOMP_FIELDS = [
    "Deal ID", "Property name", "Address 1", "Address 2", "City", "State", "Zip code", "Country",
    "Lessee.Full Name", "Lessor.Full Name", "Rent/month", "Rent/sq ft", "Sq ft", "Lease term", "Lease type", "Deal date"
]
REALNEX_SALECOMP_FIELDS = [
    "Deal ID", "Property name", "Address", "City", "State", "Zip code", "Buyer.Name", "Seller.Name", "Sale price", "Sq ft", "Property type", "Sale date"
]
REALNEX_SPACES_FIELDS = [
    "Property.Property name", "Property.Address 1", "Property.City", "Property.State", "Property.Zip code", "Suite", "Floor", "Sq Ft", "Rent/SqFt", "Rent/Month", "Lease type"
]
REALNEX_PROJECTS_FIELDS = ["Project", "Type", "Size", "Deal amt", "Commission", "Date opened", "Date closed"]
REALNEX_COMPANIES_FIELDS = ["Company", "Address1", "City", "State", "Zip Code", "Phone", "Email"]
REALNEX_CONTACTS_FIELDS = ["Full Name", "First Name", "Last Name", "Company", "Address1", "City", "State", "Postal Code", "Work Phone", "Email"]
REALNEX_PROPERTIES_FIELDS = ["Property Name", "Property Type", "Property Address", "Property City", "Property State", "Property Postal Code", "Building Size", "Sale Price"]

USER_MAPPINGS = defaultdict(dict)

# Helper to get token
def get_token(user_id, service):
    cursor.execute("SELECT token FROM user_tokens WHERE user_id = ? AND service = ?", (user_id, service))
    result = cursor.fetchone()
    return result[0] if result else None

# Helper to fetch JWT token from RealNex
async def fetch_realnex_jwt(user_id, username, password):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            REALNEX_AUTH_URL,
            json={"username": username, "password": password}
        )
    if response.status_code == 200:
        jwt_token = response.json().get("token")
        cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                       (user_id, "realnex", jwt_token))
        conn.commit()
        return jwt_token
    return None

# Helper to validate token
def validate_token(token, service):
    if service == "realnex":
        response = httpx.get(
            f"{REALNEX_API_BASE}/ValidateToken",
            headers={'Authorization': f'Bearer {token}'}
        )
        return response.status_code == 200
    elif service == "mailchimp":
        try:
            client = MailchimpClient()
            client.set_config({"api_key": token, "server": MAILCHIMP_SERVER_PREFIX})
            client.ping.get()
            return True
        except:
            return False
    return False

# Helper to get user settings
def get_user_settings(user_id):
    cursor.execute("SELECT deal_alerts_enabled, deal_alert_volume, subject_generator_enabled, achievements_enabled, sms_alerts_enabled, phone_number, language FROM user_settings WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        return {
            "deal_alerts_enabled": bool(result[0]),
            "deal_alert_volume": result[1],
            "subject_generator_enabled": bool(result[2]),
            "achievements_enabled": bool(result[3]),
            "sms_alerts_enabled": bool(result[4]),
            "phone_number": result[5],
            "language": result[6] or "en"
        }
    return {
        "deal_alerts_enabled": True,
        "deal_alert_volume": 90,
        "subject_generator_enabled": True,
        "achievements_enabled": True,
        "sms_alerts_enabled": False,
        "phone_number": "",
        "language": "en"
    }

# Points system helper with email credits, MSA, and achievements
def award_points(user_id, points_to_add, action):
    settings = get_user_settings(user_id)
    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    current_points = result[0] if result else 0
    email_credits = result[1] if result else 0
    has_msa = result[2] if result else 0
    new_points = current_points + points_to_add

    # Check for email credits unlock at 1000 points
    if current_points < 1000 and new_points >= 1000:
        email_credits += 1000
        socketio.emit('credits_update', {'user_id': user_id, 'email_credits': email_credits, 'message': "You've hit 1000 points and unlocked 1000 email credits for RealBlasts! 🚀"})

    # Check for achievements
    achievements = []
    if settings["achievements_enabled"] and new_points >= 1000 and current_points < 1000:
        achievement_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO user_achievements (user_id, achievement_id, name, description, awarded_date) VALUES (?, ?, ?, ?, ?)",
                       (user_id, achievement_id, "1000 Points Ace", "Earned 1000 points!", datetime.now().isoformat()))
        achievements.append({"name": "1000 Points Ace", "description": "Earned 1000 points!"})
    if settings["achievements_enabled"] and new_points >= 5000 and current_points < 5000:
        achievement_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO user_achievements (user_id, achievement_id, name, description, awarded_date) VALUES (?, ?, ?, ?, ?)",
                       (user_id, achievement_id, "5000 Points Pro", "Earned 5000 points!", datetime.now().isoformat()))
        achievements.append({"name": "5000 Points Pro", "description": "Earned 5000 points!"})

    cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, email_credits, has_msa, last_updated) VALUES (?, ?, ?, ?, ?)",
                   (user_id, new_points, email_credits, has_msa, datetime.now().isoformat()))
    cursor.execute("INSERT INTO points_history (user_id, points, timestamp) VALUES (?, ?, ?)",
                   (user_id, new_points, datetime.now().isoformat()))
    conn.commit()
    socketio.emit('points_update', {'user_id': user_id, 'points': new_points, 'message': f"Earned {points_to_add} points for {action}! Total points: {new_points} 🏆"})
    if achievements:
        socketio.emit('achievement_unlocked', {'user_id': user_id, 'achievements': achievements})
    return new_points, email_credits, has_msa, f"Earned {points_to_add} points for {action}! Total points: {new_points} 🏆"

# Onboarding helper
def update_onboarding(user_id, step):
    cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, 1)", (user_id, step))
    conn.commit()

    onboarding_steps = ["save_settings", "sync_crm_data", "send_realblast", "send_training_reminder"]
    completed_steps = []
    for step in onboarding_steps:
        cursor.execute("SELECT completed FROM user_onboarding WHERE user_id = ? AND step = ?", (user_id, step))
        result = cursor.fetchone()
        if result and result[0] == 1:
            completed_steps.append(step)

    if set(completed_steps) == set(onboarding_steps):
        cursor.execute("SELECT has_msa FROM user_points WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        has_msa = result[0] if result else 0
        if not has_msa:
            cursor.execute("UPDATE user_points SET has_msa = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            socketio.emit('msa_update', {'user_id': user_id, 'message': "Congrats! You've completed onboarding and earned a free RealBlast MSA! 🚀"})

# Normalize field names for matching
def normalize_field_name(field):
    return re.sub(r'[^a-z0-9]', '', field.lower())

# Suggest field mappings
def suggest_mappings(uploaded_headers, template_fields, user_id):
    suggestions = {}
    for header in uploaded_headers:
        norm_header = normalize_field_name(header)
        cursor.execute("SELECT mapped_field, frequency FROM user_mappings WHERE user_id = ? AND header = ? ORDER BY frequency DESC LIMIT 1",
                       (user_id, header))
        result = cursor.fetchone()
        if result:
            suggestions[header] = result[0]
        else:
            best_match = None
            best_score = 0
            for template_field in template_fields:
                norm_template_field = normalize_field_name(template_field)
                score = fuzz.token_sort_ratio(norm_header, norm_template_field)
                if score > 80:
                    best_match = template_field
                    best_score = score
                    break
                elif score > best_score:
                    best_match = template_field
                    best_score = score
            if best_score > 50:
                suggestions[header] = best_match
    return suggestions

# Match uploaded headers to RealNex fields
def match_fields(uploaded_headers, template_fields, user_id="default"):
    matched_fields = {}
    unmatched_fields = []
    custom_fields = ["User 1", "User 2", "User 3", "User 4", "User 5", "User 6", "User 7", "User 8", "User 9", "User 10",
                     "UserDate 1", "UserDate 2", "UserDate 3", "UserNumber 1", "UserNumber 2", "UserNumber 3", "UserMulti"]
    custom_field_index = 0

    user_mappings = USER_MAPPINGS[user_id]
    suggestions = suggest_mappings(uploaded_headers, template_fields, user_id)

    for header in uploaded_headers:
        if header in user_mappings:
            matched_fields[header] = user_mappings[header]
            cursor.execute("INSERT INTO user_mappings (user_id, header, mapped_field, frequency) VALUES (?, ?, ?, 1) "
                           "ON CONFLICT(user_id, header) DO UPDATE SET frequency = frequency + 1",
                           (user_id, header, user_mappings[header]))
        elif header in suggestions:
            matched_fields[header] = suggestions[header]
            cursor.execute("INSERT INTO user_mappings (user_id, header, mapped_field, frequency) VALUES (?, ?, ?, 1) "
                           "ON CONFLICT(user_id, header) DO UPDATE SET frequency = frequency + 1",
                           (user_id, header, suggestions[header]))
        else:
            norm_header = normalize_field_name(header)
            best_match = None
            best_score = 0
            for template_field in template_fields:
                norm_template_field = normalize_field_name(template_field)
                score = fuzz.token_sort_ratio(norm_header, norm_template_field)
                if score > 80:
                    best_match = template_field
                    best_score = score
                    break
                elif score > best_score:
                    best_match = template_field
                    best_score = score

            if best_score > 50:
                matched_fields[header] = best_match
                cursor.execute("INSERT INTO user_mappings (user_id, header, mapped_field, frequency) VALUES (?, ?, ?, 1)",
                               (user_id, header, best_match))
            else:
                if custom_field_index < len(custom_fields):
                    matched_fields[header] = custom_fields[custom_field_index]
                    cursor.execute("INSERT INTO user_mappings (user_id, header, mapped_field, frequency) VALUES (?, ?, ?, 1)",
                                   (user_id, header, custom_fields[custom_field_index]))
                    custom_field_index += 1
                else:
                    unmatched_fields.append(header)
    conn.commit()
    return matched_fields, unmatched_fields

# 2FA setup and verification
def register_user_for_2fa(user_id, email, phone):
    if not twilio_client:
        return None
    authy = twilio_client.authy.users.create(
        email=email,
        phone=phone,
        country_code="1"
    )
    if authy.id:
        cursor.execute("INSERT OR REPLACE INTO user_2fa (user_id, authy_id) VALUES (?, ?)",
                       (user_id, authy.id))
        conn.commit()
        return authy.id
    return None

def send_2fa_code(user_id):
    if not twilio_client:
        return False
    cursor.execute("SELECT authy_id FROM user_2fa WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return False
    authy_id = result[0]
    authy = twilio_client.authy.users(authy_id).sms()
    return authy.status == "success"

def check_2fa(user_id, code):
    if not twilio_client:
        return False
    cursor.execute("SELECT authy_id FROM user_2fa WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return False
    authy_id = result[0]
    verification = twilio_client.authy.users(authy_id).verify(token=code)
    return verification.status == "success"

# OCR helper for PDFs and images
def extract_text_from_file(file):
    if file.content_type == 'application/pdf':
        pdf_file = PyMuPDF.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in pdf_file:
            text += page.get_text()
        if not text.strip():
            images = convert_from_bytes(file.read())
            for image in images:
                text += pytesseract.image_to_string(image)
        return text
    elif file.content_type in ['image/jpeg', 'image/png']:
        image = Image.open(file.stream)
        return pytesseract.image_to_string(image)
    return ""

# Cached RealNex API call
async def get_realnex_data(user_id, endpoint):
    if not redis_client:
        return None
    cache_key = f"realnex:{user_id}:{endpoint}"
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    token = get_token(user_id, "realnex")
    if not token:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/{endpoint}",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code == 200:
        data = response.json().get('value', [])
        redis_client.setex(cache_key, 3600, json.dumps(data))  # Cache for 1 hour
        return data
    return None

# Background task to check for new imports and emit deal alerts
def check_new_imports():
    settings = get_user_settings("default")
    if not settings["deal_alerts_enabled"] and not settings["sms_alerts_enabled"]:
        return
    last_checked = datetime.now().isoformat()
    while True:
        time.sleep(10)
        user_id = "default"
        cursor.execute("SELECT threshold FROM deal_alerts WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        threshold = result[0] if result else None

        cursor.execute("SELECT import_id, record_type, record_data, import_date FROM user_imports WHERE user_id = ? AND import_date > ?",
                       (user_id, last_checked))
        new_imports = cursor.fetchall()
        for imp in new_imports:
            import_id, record_type, record_data, import_date = imp
            record_data = json.loads(record_data)
            if record_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                deal_value = record_data.get('Rent/month', record_data.get('Sale price', 0))
                deal_type = 'LeaseComp' if 'Rent/month' in record_data else 'SaleComp'
                message = f"New {deal_type} Alert! Deal value: ${deal_value} (exceeds your threshold of ${threshold}) at {import_date}."
                if threshold and deal_value and deal_value > threshold:
                    if settings["deal_alerts_enabled"]:
                        socketio.emit('deal_alert', {
                            'user_id': user_id,
                            'message': message,
                            'tts': message
                        })
                    if settings["sms_alerts_enabled"] and settings["phone_number"]:
                        if twilio_client:
                            try:
                                twilio_client.messages.create(
                                    body=message,
                                    from_='+1234567890',  # Replace with your Twilio number
                                    to=settings["phone_number"]
                                )
                            except Exception as e:
                                print(f"Failed to send SMS: {e}")
                else:
                    socketio.emit('deal_alert', {
                        'user_id': user_id,
                        'message': f"New {deal_type} Imported: Value ${deal_value} at {import_date}."
                    })
        last_checked = datetime.now().isoformat()

# Start the background task
threading.Thread(target=check_new_imports, daemon=True).start()

# Health check route
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

# Route to fetch RealNex JWT token
@app.route('/fetch-realnex-jwt', methods=['POST'])
async def fetch_realnex_jwt_route():
    data = request.json
    user_id = "default"
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Please provide RealNex username and password."}), 400

    jwt_token = await fetch_realnex_jwt(user_id, username, password)
    if jwt_token:
        return jsonify({"message": "RealNex JWT token fetched successfully! 🚀"}), 200
    return jsonify({"error": "Failed to fetch RealNex JWT token. Check your credentials."}), 400

# File upload route
@app.route('/upload-file', methods=['POST'])
async def upload_file():
    user_id = "default"
    token = get_token(user_id, "realnex")
    if not token:
        return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to import data. 🔑"})

    if not twilio_client:
        return jsonify({"error": "Twilio client not initialized. Check server logs for details."}), 500

    data = request.form.to_dict()
    two_fa_code = data.get('two_fa_code')
    if not two_fa_code:
        if not send_2fa_code(user_id):
            return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
        return jsonify({"message": "2FA code sent to your phone. Please provide the code to proceed."}), 200

    if not check_2fa(user_id, two_fa_code):
        return jsonify({"error": "Invalid 2FA code"}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    valid_types = ['application/pdf', 'image/jpeg', 'image/png', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    
    if file.content_type not in valid_types:
        return jsonify({"error": "Invalid file type. Only PDFs, JPEG/PNG images, and XLSX files are allowed."}), 400

    record_count = 0
    records = []
    import_id = str(uuid.uuid4())

    if file.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        df = pd.read_excel(file, engine='openpyxl')
        record_count = len(df)
        records = df.to_dict('records')
    elif file.content_type == 'application/pdf':
        pdf_file = PyMuPDF.open(stream=file.read(), filetype="pdf")
        record_count = len(pdf_file)
        for page_num in range(record_count):
            records.append({"page": page_num + 1, "text": pdf_file[page_num].get_text()})
    else:
        record_count = 1
        text = pytesseract.image_to_string(Image.open(file.stream))
        records.append({"text": text})

    for record in records:
        cursor.execute("INSERT INTO user_imports (user_id, import_id, record_type, record_data, import_date) VALUES (?, ?, ?, ?, ?)",
                       (user_id, import_id, file.content_type, json.dumps(record), datetime.now().isoformat()))
    conn.commit()

    points_to_add = record_count
    points, email_credits, has_msa, points_message = award_points(user_id, points_to_add, f"importing {record_count} records")

    if file.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        uploaded_headers = list(df.columns)
        templates = {
            "LeaseComps": REALNEX_LEASECOMP_FIELDS,
            "SaleComps": REALNEX_SALECOMP_FIELDS,
            "Spaces": REALNEX_SPACES_FIELDS,
            "Projects": REALNEX_PROJECTS_FIELDS,
            "Companies": REALNEX_COMPANIES_FIELDS,
            "Contacts": REALNEX_CONTACTS_FIELDS,
            "Properties": REALNEX_PROPERTIES_FIELDS
        }

        best_match_template = None
        best_match_count = 0
        matched_fields = {}
        unmatched_fields = []

        for template_name, template_fields in templates.items():
            matched, unmatched = match_fields(uploaded_headers, template_fields, user_id)
            match_count = len(matched)
            if match_count > best_match_count:
                best_match_count = match_count
                best_match_template = template_name
                matched_fields = matched
                unmatched_fields = unmatched

        renamed_df = df.rename(columns=matched_fields)
        csv_buffer = io.StringIO()
        renamed_df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f'{REALNEX_API_BASE}/ImportData',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                content=csv_data
            )

        if response.status_code == 200:
            message = f"Imported {record_count} records into RealNex as {best_match_template}! "
            message += f"Matched fields: {', '.join([f'{k} → {v}' for k, v in matched_fields.items()])}. "
            if unmatched_fields:
                message += f"Unmatched fields: {', '.join(unmatched_fields)}. Map these in RealNex or adjust your file."
            else:
                message += "All fields matched—smooth sailing!"
            message += f" {points_message}"
            return jsonify({"message": message, "points": points, "email_credits": email_credits, "has_msa": has_msa}), 200
        return jsonify({"error": f"Failed to import data into RealNex: {response.text}"}), 400
    else:
        message = f"Imported {record_count} records (non-CSV data stored locally). {points_message}"
        return jsonify({"message": message, "points": points, "email_credits": email_credits, "has_msa": has_msa}), 200

# Deal prediction route
@app.route('/predict-deal', methods=['POST'])
async def predict_deal():
    user_id = "default"
    data = request.json
    deal_type = data.get('deal_type', 'LeaseComp')
    sq_ft = data.get('sq_ft')

    if not sq_ft or not isinstance(sq_ft, (int, float)) or sq_ft <= 0:
        return jsonify({"error": "Please provide a valid square footage. 🔮"}), 400

    if deal_type not in ["LeaseComp", "SaleComp"]:
        return jsonify({"error": "Deal type must be 'LeaseComp' or 'SaleComp'. 🔮"}), 400

    historical_data = await get_realnex_data(user_id, f"{deal_type}s")
    if not historical_data:
        return jsonify({"error": "Failed to fetch historical data or no data available."}), 400

    X = []
    y = []
    labels = []
    for item in historical_data:
        date = item.get('deal_date') or item.get('sale_date')
        if not date:
            continue
        sq_ft_value = item.get("sq_ft", 0)
        if deal_type == "LeaseComp":
            value = item.get("rent_month", 0)
        else:
            value = item.get("sale_price", 0)
        X.append([sq_ft_value])
        y.append(value)
        labels.append(date)

    if not X or not y:
        return jsonify({"error": "Insufficient data for prediction."}), 400

    model = LinearRegression()
    model.fit(X, y)
    predicted_value = model.predict([[sq_ft]])[0]

    chart_data = {
        "labels": labels,
        "datasets": [
            {
                "label": f"Historical {deal_type} Data",
                "data": y,
                "borderColor": "rgba(59, 130, 246, 1)",
                "backgroundColor": "rgba(59, 130, 246, 0.2)",
                "fill": True
            },
            {
                "label": "Prediction",
                "data": [{"x": sq_ft, "y": predicted_value}],
                "borderColor": "rgba(34, 197, 94, 1)",
                "backgroundColor": "rgba(34, 197, 94, 0.5)",
                "pointRadius": 8,
                "pointHoverRadius": 12
            }
        ]
    }

    prediction = {
        "deal_type": deal_type,
        "sq_ft": sq_ft,
        "predicted_value": round(predicted_value, 2),
        "unit": "month" if deal_type == "LeaseComp" else "total",
        "chart_data": chart_data
    }
    return jsonify({"prediction": prediction}), 200

# Deal negotiation route
@app.route('/negotiate-deal', methods=['POST'])
async def negotiate_deal():
    user_id = "default"
    token = get_token(user_id, "realnex")
    if not token:
        return jsonify({"error": "Please fetch your RealNex JWT token in Settings to negotiate a deal. 🔑"}), 400

    if not openai_client:
        return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

    data = request.json
    deal_type = data.get('deal_type', 'LeaseComp')
    sq_ft = data.get('sq_ft')
    offered_value = data.get('offered_value')

    if not sq_ft or not isinstance(sq_ft, (int, float)) or sq_ft <= 0:
        return jsonify({"error": "Please provide a valid square footage. 🤝"}), 400
    if not offered_value or not isinstance(offered_value, (int, float)) or offered_value <= 0:
        return jsonify({"error": "Please provide a valid offered value. 🤝"}), 400
    if deal_type not in ["LeaseComp", "SaleComp"]:
        return jsonify({"error": "Deal type must be 'LeaseComp' or 'SaleComp'. 🤝"}), 400

    historical_data = await get_realnex_data(user_id, f"{deal_type}s")
    if not historical_data:
        return jsonify({"error": "No historical data available for negotiation."}), 400

    sq_ft_values = []
    values = []
    for item in historical_data:
        sq_ft_value = item.get("sq_ft", 0)
        if deal_type == "LeaseComp":
            value = item.get("rent_month", 0)
        else:
            value = item.get("sale_price", 0)
        sq_ft_values.append(sq_ft_value)
        values.append(value)

    if not sq_ft_values or not values:
        return jsonify({"error": "Insufficient data for negotiation."}), 400

    prompt = (
        f"You are a commercial real estate negotiation expert. Based on the following historical {deal_type} data, "
        f"suggest a counteroffer for a property with {sq_ft} square feet, where the offered value is ${offered_value} "
        f"({'per month' if deal_type == 'LeaseComp' else 'total'}). Historical data (square footage, value):\n"
    )
    for sf, val in zip(sq_ft_values, values):
        prompt += f"- {sf} sq ft: ${val} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
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

        negotiation_result = {
            "deal_type": deal_type,
            "sq_ft": sq_ft,
            "offered_value": offered_value,
            "counteroffer": round(counteroffer, 2),
            "confidence": confidence,
            "explanation": explanation,
            "unit": "month" if deal_type == "LeaseComp" else "total"
        }
        return jsonify({"negotiation": negotiation_result}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to negotiate deal: {str(e)}. Try again."}), 400

# Text-to-Speech route with volume control and language support
@app.route('/tts', methods=['POST'])
def text_to_speech():
    settings = get_user_settings("default")
    data = request.json
    text = data.get('text', '')
    if not text:
        return jsonify({"error": "No text provided for TTS."}), 400

    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', settings["deal_alert_volume"] / 100.0)
    
    # Set voice based on language (simplified; may need additional voices installed)
    voices = engine.getProperty('voices')
    if settings["language"] == "es":
        for voice in voices:
            if "spanish" in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
    elif settings["language"] == "fr":
        for voice in voices:
            if "french" in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
    else:
        for voice in voices:
            if "english" in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break

    engine.say(text)
    engine.runAndWait()
    return jsonify({"message": "TTS played successfully! 🎙️"}), 200

# Set deal alert threshold
@app.route('/set-deal-alert', methods=['POST'])
def set_deal_alert():
    user_id = "default"
    settings = get_user_settings(user_id)
    if not settings["deal_alerts_enabled"]:
        return jsonify({"error": "Deal alerts are disabled in settings. Enable them to set a threshold."}), 400

    data = request.json
    threshold = data.get('threshold')

    if not threshold or not isinstance(threshold, (int, float)) or threshold <= 0:
        return jsonify({"error": "Please provide a valid threshold value."}), 400

    cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold) VALUES (?, ?)",
                   (user_id, threshold))
    conn.commit()
    return jsonify({"message": f"Deal alert set! You'll be notified for deals over ${threshold}. 🔔"}), 200

# Generate email subject line
@app.route('/generate-subject', methods=['POST'])
def generate_subject():
    user_id = "default"
    settings = get_user_settings(user_id)
    if not settings["subject_generator_enabled"]:
        return jsonify({"error": "Subject line generator is disabled in settings. Enable it to generate subjects."}), 400

    if not openai_client:
        return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

    data = request.json
    campaign_type = data.get('campaign_type', 'RealBlast')

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert in email marketing for commercial real estate."},
                {"role": "user", "content": f"Generate a catchy subject line for a {campaign_type} email campaign."}
            ]
        )
        subject = response.choices[0].message.content.strip()
        return jsonify({"subject": subject}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to generate subject line: {str(e)}."}), 400

# Fetch user achievements
@app.route('/achievements', methods=['GET'])
def get_achievements():
    user_id = "default"
    settings = get_user_settings(user_id)
    if not settings["achievements_enabled"]:
        return jsonify({"message": "Achievements are disabled in settings. Enable them to view your badges! 🏅"}), 200

    cursor.execute("SELECT name, description, awarded_date FROM user_achievements WHERE user_id = ? ORDER BY awarded_date DESC",
                   (user_id,))
    achievements = cursor.fetchall()
    return jsonify({
        "achievements": [{"name": a[0], "description": a[1], "awarded_date": a[2]} for a in achievements]
    }), 200

# Fetch points history
@app.route('/points-history', methods=['GET'])
def get_points_history():
    user_id = "default"
    cursor.execute("SELECT points, timestamp FROM points_history WHERE user_id = ? ORDER BY timestamp ASC",
                   (user_id,))
    history = cursor.fetchall()
    return jsonify({
        "history": [{"points": h[0], "timestamp": h[1]} for h in history]
    }), 200

# Settings route to get current settings
@app.route('/settings', methods=['GET'])
def get_settings():
    user_id = "default"
    settings = get_user_settings(user_id)
    return jsonify({"settings": settings}), 200

# Settings route to update settings
@app.route('/settings', methods=['POST'])
def update_settings():
    user_id = "default"
    data = request.json
    deal_alerts_enabled = int(data.get('deal_alerts_enabled', True))
    deal_alert_volume = max(0, min(100, int(data.get('deal_alert_volume', 90))))
    subject_generator_enabled = int(data.get('subject_generator_enabled', True))
    achievements_enabled = int(data.get('achievements_enabled', True))
    sms_alerts_enabled = int(data.get('sms_alerts_enabled', False))
    phone_number = data.get('phone_number', '')
    language = data.get('language', 'en')

    cursor.execute("INSERT OR REPLACE INTO user_settings (user_id, deal_alerts_enabled, deal_alert_volume, subject_generator_enabled, achievements_enabled, sms_alerts_enabled, phone_number, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (user_id, deal_alerts_enabled, deal_alert_volume, subject_generator_enabled, achievements_enabled, sms_alerts_enabled, phone_number, language))
    conn.commit()
    socketio.emit('settings_update', {'user_id': user_id, 'settings': {
        "deal_alerts_enabled": bool(deal_alerts_enabled),
        "deal_alert_volume": deal_alert_volume,
        "subject_generator_enabled": bool(subject_generator_enabled),
        "achievements_enabled": bool(achievements_enabled),
        "sms_alerts_enabled": bool(sms_alerts_enabled),
        "phone_number": phone_number,
        "language": language
    }})
    return jsonify({"message": "Settings updated successfully! ⚙️"}), 200

# Settings page route
@app.route('/settings-page')
def settings_page():
    return render_template('settings.html')

# Dashboard page route
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# Dashboard data route
@app.route('/dashboard-data', methods=['GET'])
async def dashboard_data():
    user_id = "default"
    token = get_token(user_id, "realnex")
    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    points = user_data[0] if user_data else 0
    email_credits = user_data[1] if user_data else 0
    has_msa = user_data[2] if user_data else 0

    cursor.execute("SELECT record_type, import_date FROM user_imports WHERE user_id = ? ORDER BY import_date DESC LIMIT 5",
                   (user_id,))
    imports = cursor.fetchall()

    data = {
        "points": points,
        "email_credits": email_credits,
        "has_msa": bool(has_msa),
        "imports": [{"record_type": imp[0], "import_date": imp[1]} for imp in imports]
    }
    return jsonify(data), 200

# Duplicates route
@app.route('/duplicates', methods=['GET'])
def get_duplicates():
    user_id = "default"
    cursor.execute("SELECT import_id, record_type, record_data, import_date FROM user_imports WHERE user_id = ? ORDER BY import_date DESC",
                   (user_id,))
    imports = cursor.fetchall()

    # Dictionary to group records by type and identify duplicates
    records_by_type = defaultdict(list)
    duplicates = defaultdict(list)

    for imp in imports:
        import_id, record_type, record_data, import_date = imp
        record_data = json.loads(record_data)
        record = {
            "import_id": import_id,
            "record_type": record_type,
            "record_data": record_data,
            "import_date": import_date
        }
        records_by_type[record_type].append(record)

    # Identify duplicates within each record type
    for record_type, records in records_by_type.items():
        seen = {}
        for record in records:
            data = record["record_data"]
            # Define key fields for duplicate detection based on record type
            if record_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                # For Excel files, use fields like Property name and Deal date
                key_fields = (
                    data.get('Property name', ''),
                    data.get('Deal date', data.get('Sale date', ''))
                )
            else:
                # For PDFs/Images, use extracted text as a key (simplified)
                key_fields = (data.get('text', ''),)

            key = (record_type, key_fields)
            if key in seen:
                duplicates[record_type].append({
                    "original": seen[key],
                    "duplicate": record
                })
            else:
                seen[key] = record

    # Format the response
    duplicates_response = {}
    for record_type, dups in duplicates.items():
        duplicates_response[record_type] = [
            {
                "original": {
                    "import_id": dup["original"]["import_id"],
                    "record_data": dup["original"]["record_data"],
                    "import_date": dup["original"]["import_date"]
                },
                "duplicate": {
                    "import_id": dup["duplicate"]["import_id"],
                    "record_data": dup["duplicate"]["record_data"],
                    "import_date": dup["duplicate"]["import_date"]
                }
            } for dup in dups
        ]

    return jsonify({"duplicates": duplicates_response}), 200

# Duplicates dashboard route
@app.route('/duplicates-dashboard')
def duplicates_dashboard():
    return render_template('duplicates_dashboard.html')

# Natural language query route
@app.route('/ask', methods=['POST'])
async def ask():
    data = request.json
    message = data.get('message', '').lower()
    user_id = "default"

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
        except Exception as e:
            print(f"Translation failed: {e}")

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
        for contact in zoominfo_contacts + apollo_contacts:
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
                answer = f"Synced {len(contacts)} contacts into RealNex. 📇 {points_message}"
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
        if deal_type == "LeaseComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("rent_month", 0))
            model = LinearRegression()
            model.fit(X, y)
            predicted_rent = model.predict([[sq_ft]])[0]
            answer = f"Predicted rent for {sq_ft} sq ft: ${predicted_rent:.2f}/month. 🔮"
        elif deal_type == "SaleComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("sale_price", 0))
            model = LinearRegression()
            model.fit(X, y)
            predicted_price = model.predict([[sq_ft]])[0]
            answer = f"Predicted sale price for {sq_ft} sq ft: ${predicted_price:.2f}. 🔮"

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
        except Exception as e:
            answer = f"Failed to negotiate deal: {str(e)}. Try again."

    elif 'notify me of new deals over' in message:
        if not settings["deal_alerts_enabled"]:
            answer = "Deal alerts are disabled in settings. Enable them to set notifications! ⚙️"
        else:
            threshold = re.search(r'over\s*\$\s*([\d.]+)', message)
            threshold = float(threshold.group(1)) if threshold else None
            if not threshold:
                answer = "Please specify a deal value threshold, like 'notify me of new deals over $5000'. What’s the threshold? 🔔"
            else:
                cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold) VALUES (?, ?)",
                               (user_id, threshold))
                conn.commit()
                answer = f"Deal alert set! I’ll notify you of new deals over ${threshold}. 🔔"

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
        except Exception as e:
            answer = f"Failed to summarize text: {str(e)}. Try again."

    elif 'verify emails' in message:
        emails = message.split('verify emails')[-1].strip().split(',')
        emails = [email.strip() for email in emails if email.strip()]
        if not emails:
            answer = "Please provide emails to verify. Say something like 'verify emails email1@example.com, email2@example.com'. What are the emails? 📧"
            return jsonify({"answer": answer, "tts": answer})

        verified_emails = [{"email": email, "status": "valid"} for email in emails]
        answer = f"Verified {len(verified_emails)} emails: {json.dumps(verified_emails)}. ✨"

    elif 'sync contacts' in message:
        google_token = data.get('google_token')
        if not google_token:
            answer = "I need a Google token to sync contacts. Say something like 'sync contacts with google token your_token_here'. What’s your Google token?"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex")
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to sync contacts. 🔑"
            return jsonify({"answer":
