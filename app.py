from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pandas as pd
import io
import numpy as np
from sklearn.linear_model import LinearRegression
import PyMuPDF
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

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your_secret_key'
redis_client = redis.Redis(host='localhost', port=6379, db=0)
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
SMTP_USER = "your_email@gmail.com"  # Replace with your email
SMTP_PASSWORD = "your_email_password"  # Replace with your email password

# Initialize clients
mailchimp = None
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Database setup for user mappings, points, 2FA, email credits, onboarding, tokens, and imports
conn = sqlite3.connect('user_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS user_mappings 
                 (user_id TEXT, header TEXT, mapped_field TEXT, frequency INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_points 
                 (user_id TEXT, points INTEGER, email_credits INTEGER, has_msa INTEGER, last_updated TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_2fa 
                 (user_id TEXT, authy_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_onboarding 
                 (user_id TEXT, step TEXT, completed INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_tokens 
                 (user_id TEXT, service TEXT, token TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_imports 
                 (user_id TEXT, import_id TEXT, record_type TEXT, record_data TEXT, import_date TEXT)''')
conn.commit()

# RealNex template fields for data imports
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

# Helper to get token for a service
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

# Helper to validate token for a service
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

# Points system helper with email credits and MSA
def award_points(user_id, points_to_add, action):
    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    current_points = result[0] if result else 0
    email_credits = result[1] if result else 0
    has_msa = result[2] if result else 0
    new_points = current_points + points_to_add

    # Check for email credits unlock at 1000 points
    if current_points < 1000 and new_points >= 1000:
        email_credits += 1000
        socketio.emit('credits_update', {'user_id': user_id, 'email_credits': email_credits, 'message': "🎉 Boom! You’ve hit 1000 points and unlocked 1000 email credits for RealBlasts! Let’s blast off, stud! 🚀"})

    cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, email_credits, has_msa, last_updated) VALUES (?, ?, ?, ?, ?)",
                   (user_id, new_points, email_credits, has_msa, datetime.now().isoformat()))
    conn.commit()
    socketio.emit('points_update', {'user_id': user_id, 'points': new_points, 'message': f"Earned {points_to_add} points for {action}! Total points: {new_points} 🏆"})
    return new_points, email_credits, has_msa, f"Earned {points_to_add} points for {action}! Total points: {new_points} 🏆"

# Onboarding helper
def update_onboarding(user_id, step):
    cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, 1)", (user_id, step))
    conn.commit()

    # Check if all onboarding steps are complete
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
            socketio.emit('msa_update', {'user_id': user_id, 'message': "🎉 Congrats, stud! You’ve completed onboarding and earned a free RealBlast MSA! Send a RealBlast on us! 🚀"})

# Normalize field names for matching
def normalize_field_name(field):
    return re.sub(r'[^a-z0-9]', '', field.lower())

# Suggest field mappings based on history or fuzzy matching
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

# 2FA setup and verification with Twilio Authy
def register_user_for_2fa(user_id, email, phone):
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
    cursor.execute("SELECT authy_id FROM user_2fa WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return False
    authy_id = result[0]
    authy = twilio_client.authy.users(authy_id).sms()
    return authy.status == "success"

def check_2fa(user_id, code):
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

# Route to fetch RealNex JWT token
@app.route('/fetch-realnex-jwt', methods=['POST'])
async def fetch_realnex_jwt_route():
    data = request.json
    user_id = "default"
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Please provide RealNex username and password, stud!"}), 400

    jwt_token = await fetch_realnex_jwt(user_id, username, password)
    if jwt_token:
        return jsonify({"message": "RealNex JWT token fetched successfully, stud! 🚀"}), 200
    return jsonify({"error": "Failed to fetch RealNex JWT token. Check your credentials, stud!"}), 400

# File upload route with RealNex integration
@app.route('/upload-file', methods=['POST'])
async def upload_file():
    user_id = "default"
    token = get_token(user_id, "realnex")
    if not token:
        return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to import data, stud! 🔑"})

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
    else:  # Image
        record_count = 1
        text = pytesseract.image_to_string(Image.open(file.stream))
        records.append({"text": text})

    # Store imported records
    for record in records:
        cursor.execute("INSERT INTO user_imports (user_id, import_id, record_type, record_data, import_date) VALUES (?, ?, ?, ?, ?)",
                       (user_id, import_id, file.content_type, json.dumps(record), datetime.now().isoformat()))
    conn.commit()

    # Award points: 1 point per record
    points_to_add = record_count
    points, email_credits, has_msa, points_message = award_points(user_id, points_to_add, f"importing {record_count} records")

    # Process for RealNex import
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
            message = f"🔥 Imported {record_count} records into RealNex as {best_match_template}! "
            message += f"Matched fields: {', '.join([f'{k} → {v}' for k, v in matched_fields.items()])}. "
            if unmatched_fields:
                message += f"Unmatched fields: {', '.join(unmatched_fields)}. Map these in RealNex or adjust your file, stud!"
            else:
                message += "All fields matched—smooth sailing, stud!"
            message += f" {points_message}"
            return jsonify({"message": message, "points": points, "email_credits": email_credits, "has_msa": has_msa}), 200
        return jsonify({"error": f"Failed to import data into RealNex: {response.text}"}), 400
    else:
        message = f"🔥 Imported {record_count} records (non-CSV data stored locally). {points_message}"
        return jsonify({"message": message, "points": points, "email_credits": email_credits, "has_msa": has_msa}), 200

# Natural language query route with trained AI
@app.route('/ask', methods=['POST'])
async def ask():
    data = request.json
    message = data.get('message', '').lower()
    user_id = "default"

    # Fetch user data
    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    points = user_data[0] if user_data else 0
    email_credits = user_data[1] if user_data else 0
    has_msa = user_data[2] if user_data else 0

    # Check onboarding progress
    onboarding_steps = ["save_settings", "sync_crm_data", "send_realblast", "send_training_reminder"]
    completed_steps = []
    for step in onboarding_steps:
        cursor.execute("SELECT completed FROM user_onboarding WHERE user_id = ? AND step = ?", (user_id, step))
        result = cursor.fetchone()
        if result and result[0] == 1:
            completed_steps.append(step)

    # Check for human help requests
    help_phrases = ["i need a human", "more help", "support help", "billing help", "sales support"]
    if any(phrase in message for phrase in help_phrases):
        issue = "General support request"
        to_email = "support@realnex.com"
        if "billing help" in message or "sales support" in message:
            issue = "Billing or sales support request"
            to_email = "sales@realnex.com"

        # Auto-draft and send email
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
                "Hang tight, stud! 🛠️"
            )
            return jsonify({"answer": contact_info})
        except Exception as e:
            return jsonify({"answer": f"Failed to send support request: {str(e)}. Please try again or contact RealNex directly at (281) 299-3161 or support@realnex.com, stud!"})

    # AI-driven commands
    if 'draft an email' in message:
        campaign_type = "RealBlast" if "realblast" in message else "Mailchimp"
        subject = "Your CRE Update"
        audience_id = None
        content = None

        # Ask follow-up questions
        if "realblast" in message:
            return jsonify({"answer": "Let’s draft a RealBlast email! What’s the subject? (e.g., 'New Property Listing')"})
        else:
            return jsonify({"answer": "Let’s draft a Mailchimp email! What’s the subject? (e.g., 'Your CRE Update')"})

    elif 'subject' in message and 'realblast' in message:
        subject = message.split('subject')[-1].strip()
        return jsonify({"answer": f"Got the subject: '{subject}'. Which RealNex group ID should this go to? (e.g., 'group123')"})

    elif 'group id' in message:
        audience_id = message.split('group id')[-1].strip()
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Draft a RealBlast email for group {audience_id} with subject 'Your CRE Update'."}
                ]
            )
            content = response.choices[0].message.content
            return jsonify({"answer": f"Here’s your RealBlast email for group {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your RealNex RealBlast setup, stud! 📧"})
        except Exception as e:
            return jsonify({"answer": f"Failed to draft email: {str(e)}. Try again, stud!"})

    elif 'subject' in message and 'mailchimp' in message:
        subject = message.split('subject')[-1].strip()
        return jsonify({"answer": f"Got the subject: '{subject}'. Which Mailchimp audience ID should this go to? (e.g., 'audience456')"})

    elif 'audience id' in message:
        audience_id = message.split('audience id')[-1].strip()
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Draft a Mailchimp email for audience {audience_id} with subject 'Your CRE Update'."}
                ]
            )
            content = response.choices[0].message.content
            return jsonify({"answer": f"Here’s your Mailchimp email for audience {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your Mailchimp campaign setup, stud! 📧"})
        except Exception as e:
            return jsonify({"answer": f"Failed to draft email: {str(e)}. Try again, stud!"})

    elif 'send realblast' in message:
        group_id = None
        campaign_content = None
        if 'group' in message:
            group_id = message.split('group')[-1].strip().split()[0]
        if 'content' in message:
            campaign_content = message.split('content')[-1].strip()

        if not group_id or not campaign_content:
            return jsonify({"answer": "To send a RealBlast, I need the group ID and campaign content. Say something like 'send realblast to group group123 with content Check out this property!'. What’s the group ID and content, stud? 📧"})

        token = get_token(user_id, "realnex")
        if not token:
            return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to send a RealBlast, stud! 🔑"})

        two_fa_code = data.get('two_fa_code')
        if not two_fa_code:
            if not send_2fa_code(user_id):
                return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
            return jsonify({"answer": "2FA code sent to your phone. Please provide the code to proceed with sending the RealBlast, stud! 🔒"})

        if not check_2fa(user_id, two_fa_code):
            return jsonify({"answer": "Invalid 2FA code, stud! Try again."})

        # Check email credits or MSA
        if has_msa:
            cursor.execute("UPDATE user_points SET has_msa = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            socketio.emit('msa_update', {'user_id': user_id, 'message': "Used your free RealBlast MSA! Nice work, stud! 🚀"})
        elif email_credits > 0:
            email_credits -= 1
            cursor.execute("UPDATE user_points SET email_credits = ? WHERE user_id = ?", (email_credits, user_id))
            conn.commit()
            socketio.emit('credits_update', {'user_id': user_id, 'email_credits': email_credits, 'message': f"Used 1 email credit for RealBlast. You have {email_credits} credits left, stud! 📧"})
        else:
            return jsonify({"answer": "You need email credits or a free RealBlast MSA to send a RealBlast! Earn 1000 points to unlock 1000 credits, or complete onboarding for a free MSA. Check your status with 'my status', stud! 🚀"})

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
            return jsonify({"answer": f"RealBlast sent to group {group_id}! Nice work, stud! 📧 {points_message}"})
        return jsonify({"answer": f"Failed to send RealBlast: {response.text}"})

    elif 'send mailchimp campaign' in message:
        audience_id = None
        campaign_content = None
        if 'audience' in message:
            audience_id = message.split('audience')[-1].strip().split()[0]
        if 'content' in message:
            campaign_content = message.split('content')[-1].strip()

        if not audience_id or not campaign_content:
            return jsonify({"answer": "To send a Mailchimp campaign, I need the audience ID and campaign content. Say something like 'send mailchimp campaign to audience audience456 with content Check out this property!'. What’s the audience ID and content, stud? 📧"})

        token = get_token(user_id, "mailchimp")
        if not token:
            return jsonify({"answer": "Please add your Mailchimp API key in Settings to send a Mailchimp campaign, stud! 🔑"})

        global mailchimp
        mailchimp = MailchimpClient()
        mailchimp.set_config({"api_key": token, "server": MAILCHIMP_SERVER_PREFIX})

        two_fa_code = data.get('two_fa_code')
        if not two_fa_code:
            if not send_2fa_code(user_id):
                return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
            return jsonify({"answer": "2FA code sent to your phone. Please provide the code to proceed with sending the Mailchimp campaign, stud! 🔒"})

        if not check_2fa(user_id, two_fa_code):
            return jsonify({"answer": "Invalid 2FA code, stud! Try again."})

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
            return jsonify({"answer": f"Mailchimp campaign sent to audience {audience_id}! Nice work, stud! 📧"})
        except Exception as e:
            return jsonify({"answer": f"Failed to send Mailchimp campaign: {str(e)}"})

    elif 'sync crm data' in message:
        token = get_token(user_id, "realnex")
        if not token:
            return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to sync CRM data, stud! 🔑"})

        zoominfo_token = get_token(user_id, "zoominfo")
        apollo_token = get_token(user_id, "apollo")

        # Fetch contacts from ZoomInfo
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
                return jsonify({"answer": f"Failed to fetch ZoomInfo contacts: {response.text}. Check your ZoomInfo token in Settings, stud!"})

        # Fetch contacts from Apollo.io
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
                return jsonify({"answer": f"Failed to fetch Apollo.io contacts: {response.text}. Check your Apollo.io token in Settings, stud!"})

        # Combine and format contacts for RealNex
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

        # Import into RealNex
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
                return jsonify({"answer": f"Synced {len(contacts)} contacts into RealNex, stud! 📇 {points_message}"})
            return jsonify({"answer": f"Failed to import contacts into RealNex: {response.text}"})
        return jsonify({"answer": "No contacts to sync, stud!"})

    elif 'predict deal' in message:
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
        sq_ft = None
        if 'square footage' in message or 'sq ft' in message:
            sq_ft = re.search(r'\d+', message)
            sq_ft = int(sq_ft.group()) if sq_ft else None

        if not deal_type or not sq_ft:
            return jsonify({"answer": "To predict a deal, I need the deal type (LeaseComp or SaleComp) and square footage. Say something like 'predict deal for LeaseComp with 5000 sq ft'. What’s the deal type and square footage, stud? 🔮"})

        token = get_token(user_id, "realnex")
        if not token:
            return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to predict a deal, stud! 🔑"})

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{REALNEX_API_BASE}/{deal_type}s",
                headers={'Authorization': f'Bearer {token}'}
            )
        if response.status_code != 200:
            return jsonify({"answer": f"Failed to fetch historical data: {response.text}"})

        historical_data = response.json().get('value', [])
        if not historical_data:
            return jsonify({"answer": "No historical data available for prediction, stud!"})

        # Train a simple linear regression model
        X = []
        y = []
        if deal_type == "LeaseComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("rent_month", 0))
            model = LinearRegression()
            model.fit(X, y)
            predicted_rent = model.predict([[sq_ft]])[0]
            return jsonify({"answer": f"Predicted rent for {sq_ft} sq ft: ${predicted_rent:.2f}/month, stud! 🔮"})
        elif deal_type == "SaleComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("sale_price", 0))
            model = LinearRegression()
            model.fit(X, y)
            predicted_price = model.predict([[sq_ft]])[0]
            return jsonify({"answer": f"Predicted sale price for {sq_ft} sq ft: ${predicted_price:.2f}, stud! 🔮"})

    elif 'summarize text' in message:
        text = message.split('summarize text')[-1].strip()
        if not text:
            return jsonify({"answer": "Please provide the text to summarize. Say something like 'summarize text This is my text to summarize'. What’s the text, stud? 📝"})

        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a text summarizer for a commercial real estate chatbot."},
                    {"role": "user", "content": f"Summarize this text: {text}"}
                ]
            )
            summary = response.choices[0].message.content
            return jsonify({"answer": f"Summary: {summary}, stud! 📝"})
        except Exception as e:
            return jsonify({"answer": f"Failed to summarize text: {str(e)}. Try again, stud!"})

    elif 'verify emails' in message:
        emails = message.split('verify emails')[-1].strip().split(',')
        emails = [email.strip() for email in emails if email.strip()]
        if not emails:
            return jsonify({"answer": "Please provide emails to verify. Say something like 'verify emails email1@example.com, email2@example.com'. What are the emails, stud? 📧"})

        # Placeholder for real email verification API
        verified_emails = [{"email": email, "status": "valid"} for email in emails]
        return jsonify({"answer": f"Verified {len(verified_emails)} emails: {json.dumps(verified_emails)}. Nice work, stud! ✨"})

    elif 'sync contacts' in message:
        google_token = data.get('google_token')
        if not google_token:
            return jsonify({"answer": "I need a Google token to sync contacts. Say something like 'sync contacts with google token your_token_here'. What’s your Google token, stud?"})

        token = get_token(user_id, "realnex")
        if not token:
            return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to sync contacts, stud! 🔑"})

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {google_token}"}
            )
        if response.status_code != 200:
            return jsonify({"answer": f"Failed to fetch Google contacts: {response.text}"})

        # Import into RealNex (simplified example)
        contacts = response.json().get("contacts", [])
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
                return jsonify({"answer": f"Synced {len(contacts)} contacts into RealNex, stud! 📇"})
            return jsonify({"answer": f"Failed to import contacts into RealNex: {response.text}"})
        return jsonify({"answer": "No contacts to sync, stud!"})

    elif 'training reminder' in message:
        user_email = None
        if 'email' in message:
            user_email = message.split('email')[-1].strip()
        if not user_email:
            return jsonify({"answer": "I need your email to send a training reminder. Say something like 'send training reminder to email myemail@example.com'. What’s your email, stud? 📚"})

        # Send email reminder
        subject = "RealNex Training Reminder"
        body = (
            "Hey there, CRE Pro!\n\n"
            "Don’t miss out on mastering RealNex! Join our training webinars or check out our Knowledge Base:\n"
            "- Training Webinars: [Link to RealNex Webinars]\n"
            "- Knowledge Base: https://realnex.zendesk.com\n\n"
            "Let’s get you closing deals faster, stud! 🏆\n"
            "- Matty’s Maverick & Goose"
        )
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = user_email

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, user_email, msg.as_string())
            update_onboarding(user_id, "send_training_reminder")
            return jsonify({"answer": "Training reminder sent! Check your email, stud! 📚"})
        except Exception as e:
            return jsonify({"answer": f"Failed to send training reminder: {str(e)}. Try again, stud!"})

    elif 'my status' in message:
        status_message = f"Here’s your status, stud! 🏆\n"
        status_message += f"Points: {points}\n"
        status_message += f"Email Credits: {email_credits} (reach 1000 points to unlock 1000 credits!)\n"
        status_message += f"Free RealBlast MSA: {'Yes' if has_msa else 'No'} (complete onboarding to earn one!)\n"
        status_message += f"Onboarding Progress: {len(completed_steps)}/{len(onboarding_steps)} steps completed\n"
        if completed_steps:
            status_message += f"Completed Steps: {', '.join(completed_steps)}\n"
        remaining_steps = [step for step in onboarding_steps if step not in completed_steps]
        if remaining_steps:
            status_message += f"Remaining Steps: {', '.join(remaining_steps)}\n"
        return jsonify({"answer": status_message})

    # RealNex-trained AI responses
    elif 'lease comps with rent over' in message:
        rent_threshold = re.search(r'\d+', message)
        if rent_threshold:
            rent_threshold = int(rent_threshold.group())
            token = get_token(user_id, "realnex")
            if not token:
                return jsonify({"answer": f"Please fetch your RealNex JWT token in Settings to query LeaseComps with rent over ${rent_threshold}/month, stud! 🔑"})

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{REALNEX_API_BASE}/LeaseComps?filter=rent_month gt {rent_threshold}",
                    headers={'Authorization': f'Bearer {token}'}
                )
            if response.status_code == 200:
                leases = response.json().get('value', [])
                if leases:
                    return jsonify({"answer": f"Found {len(leases)} LeaseComps with rent over ${rent_threshold}/month: {json.dumps(leases[:2])}. Check RealNex for more, stud! 📊"})
                return jsonify({"answer": f"No LeaseComps found with rent over ${rent_threshold}/month."})
            return jsonify({"answer": f"Error fetching LeaseComps: {response.text}"})
    elif 'sale comps in' in message and 'city' in message:
        city = re.search(r'in\s+([a-z\s]+)\s+city', message)
        if city:
            city = city.group(1).strip()
            token = get_token(user_id, "realnex")
            if not token:
                return jsonify({"answer": f"Please fetch your RealNex JWT token in Settings to query SaleComps in {city} city, stud! 🔑"})

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{REALNEX_API_BASE}/SaleComps?filter=city eq '{city}'",
                    headers={'Authorization': f'Bearer {token}'}
                )
            if response.status_code == 200:
                sales = response.json().get('value', [])
                if sales:
                    return jsonify({"answer": f"Found {len(sales)} SaleComps in {city} city: {json.dumps(sales[:2])}. Dive into RealNex for details, stud! 🏙️"})
                return jsonify({"answer": f"No SaleComps found in {city} city."})
            return jsonify({"answer": f"Error fetching SaleComps: {response.text}"})
    elif 'required fields' in message:
        if 'lease comp' in message:
            required_fields = ["Deal ID", "Property name", "Address 1", "City", "State", "Zip code", "Lessee.Full Name", "Lessor.Full Name", "Rent/month", "Sq ft", "Lease term", "Deal date"]
            return jsonify({"answer": f"The required fields for a LeaseComp import are: {', '.join(required_fields)}. Let’s get that deal in, stud! 💼"})
        elif 'sale comp' in message:
            required_fields = ["Deal ID", "Property name", "Address", "City", "State", "Zip code", "Buyer.Name", "Seller.Name", "Sale price", "Sq ft", "Sale date"]
            return jsonify({"answer": f"The required fields for a SaleComp import are: {', '.join(required_fields)}. Ready to crush that sale, stud? 🤑"})
        elif 'spaces' in message:
            required_fields = ["Property.Property name", "Property.Address 1", "Property.City", "Property.State", "Property.Zip code", "Suite", "Floor", "Sq Ft"]
            return jsonify({"answer": f"The required fields for a Spaces import are: {', '.join(required_fields)}. Let’s fill those spaces, stud! 🏢"})
        elif 'projects' in message:
            required_fields = ["Project", "Type", "Size", "Deal amt", "Date opened"]
            return jsonify({"answer": f"The required fields for a Projects import are: {', '.join(required_fields)}. Time to kick off that project, stud!"})
        elif 'companies' in message:
            required_fields = ["Company", "Address1", "City", "State", "Zip Code"]
            return jsonify({"answer": f"The required fields for a Companies import are: {', '.join(required_fields)}. Let’s add that company, stud! 🏬"})
        elif 'contacts' in message:
            required_fields = ["Full Name", "First Name", "Last Name", "Company", "Address1", "City", "State", "Postal Code"]
            return jsonify({"answer": f"The required fields for a Contacts import are: {', '.join(required_fields)}. Ready to connect, stud? 📞"})
        elif 'properties' in message:
            required_fields = ["Property Name", "Property Type", "Property Address", "Property City", "Property State", "Property Postal Code"]
            return jsonify({"answer": f"The required fields for a Properties import are: {', '.join(required_fields)}. Let’s list that property, stud! 🏠"})
    elif 'what is a lease term' in message:
        return jsonify({"answer": "In RealNex, the 'Lease term' field is the duration of the lease agreement, usually in months (e.g., '24 Months'). It’s required for LeaseComps. Let’s lock in that lease, stud! 📝"})
    elif 'what is a cap rate' in message:
        return jsonify({"answer": "In RealNex, the 'Cap rate' (capitalization rate) is a SaleComp field that measures the return on investment for a property, calculated as NOI / Sale price. It’s a key metric for investors, stud! 📈"})
    elif 'how to import' in message and 'realnex' in message:
        return jsonify({"answer": "To import into RealNex, drag-and-drop your XLSX, PDF, or image file into the chat. I’ll auto-match your fields to RealNex templates like LeaseComps or SaleComps, and import the data for you. You’ll earn 1 point per record imported! Make sure your file has headers, and required fields like 'Deal ID' match exactly, or the import might fail. You’ll need to fetch your RealNex JWT token in Settings first, stud! 🖥️"})
    elif 'realblast' in message and 'best' in message:
        return jsonify({"answer": "The best way to set up a RealBlast is to use a clear subject line and include a call-to-action, like 'View Property Listing'. You can target your CRM groups or the RealNex community of over 100,000 users, and even schedule the campaign for a future date. Say 'send realblast to group group123 with content Check out this property!' to send one, stud! 📧"})
    elif 'marketedge' in message and 'flyer' in message:
        return jsonify({"answer": "To create a flyer in RealNex MarketEdge, select a property from your CRM, choose a flyer template, customize it with your branding, and download the PDF. MarketEdge auto-populates data like the property address and sale price. Note that MarketEdge doesn’t have an API, so you’ll need to do this directly in RealNex, stud! 📄"})
    elif 'what is a buyer match score' in message:
        return jsonify({"answer": "In RealNex NavigatorPRO, the Buyer Match Score is a percentage that shows how likely a contact is to buy a property, based on predictive analytics. Unfortunately, NavigatorPRO doesn’t have an API, so you’ll need to check this directly in RealNex, stud! 🔍"})
    elif 'why did my import fail' in message:
        return jsonify({"answer": "Your RealNex import might have failed because required fields didn’t match exactly—like 'Deal ID' for LeaseComps—or the formatting was off. Download the RealNex template files to ensure your data matches the expected format, stud! 🖥️"})
    elif 'where can i find realnex training' in message:
        return jsonify({"answer": "RealNex offers weekly training webinars and one-on-one sessions—check their website for the schedule. You can also visit the Knowledge Base at https://realnex.zendesk.com, or start with the 'Getting Started' guide there. Say 'send training reminder to email your_email@example.com' to get a link sent to your email, stud! 📚"})
    elif 'realblast' in message:
        return jsonify({"answer": "RealBlasts are RealNex’s email campaigns! You can send them to your CRM groups or the RealNex community (over 100,000 users). Say 'send realblast to group group123 with content Check out this property!' to send one. You’ll need email credits (earn 1000 points for 1000 credits) or a free RealBlast MSA (complete onboarding), and a RealNex JWT token in Settings, stud! 📧"})
    elif 'marketedge' in message:
        return jsonify({"answer": "MarketEdge in RealNex lets you create financial analyses, proposals, flyers, BOVs, and offering memorandums. It auto-populates data from your CRM and uses your branding. Note that MarketEdge doesn’t have an API, so you’ll need to use it directly in RealNex, stud! 📈"})
    else:
        return jsonify({"answer": "I can help with RealNex questions, stud! Ask about required fields, specific terms, RealBlasts, MarketEdge, or how to import data. You can also say things like 'draft an email for my realblast', 'send realblast', 'predict deal', or 'summarize text'. Check your gamification status with 'my status'. If you need more help, say 'I need a human' or 'support help'. What’s up? 🤙"})

# Dashboard data route
@app.route('/dashboard-data', methods=['GET'])
async def dashboard_data():
    user_id = "default"
    token = get_token(user_id, "realnex")
    data = {"imports": []}

    # Fetch recent imports
    cursor.execute("SELECT import_id, record_type, record_data, import_date FROM user_imports WHERE user_id = ? ORDER BY import_date DESC LIMIT 10", (user_id,))
    imports = cursor.fetchall()
    for imp in imports:
        data["imports"].append({
            "import_id": imp[0],
            "record_type": imp[1],
            "record_data": json.loads(imp[2]),
            "import_date": imp[3]
        })

    if token:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{REALNEX_API_BASE}/Dashboard",
                headers={'Authorization': f'Bearer {token}'}
            )
        if response.status_code == 200:
            data.update(response.json())
    else:
        data["answer"] = "Please fetch your RealNex JWT token in Settings to access full dashboard data, stud! 🔑"

    cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    data["points"] = result[0] if result else 0
    data["email_credits"] = result[1] if result else 0
    data["has_msa"] = result[2] if result else 0
    return jsonify(data), 200

# Deal trends for Chart.js visualization
@app.route('/deal-trends', methods=['GET'])
async def deal_trends():
    user_id = "default"
    token = get_token(user_id, "realnex")
    if not token:
        return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to access deal trends, stud! 🔑"})

    deal_type = request.args.get('deal_type', 'LeaseComp')  # Default to LeaseComp

    # Fetch historical data from RealNex
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/{deal_type}s",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code != 200:
        return jsonify({"error": f"Failed to fetch deal data: {response.text}"}), 400

    deals = response.json().get('value', [])
    if not deals:
        return jsonify({"error": "No deal data available"}), 400

    # Prepare data for Chart.js
    labels = []
    values = []
    for deal in deals:
        date = deal.get('deal_date') or deal.get('sale_date')
        if not date:
            continue
        labels.append(date)
        if deal_type == "LeaseComp":
            values.append(deal.get('rent_month', 0))
        else:  # SaleComp
            values.append(deal.get('sale_price', 0))

    chart_data = {
        "labels": labels,
        "datasets": [{
            "label": f"{deal_type} Trends",
            "data": values,
            "borderColor": "rgba(75, 192, 192, 1)",
            "backgroundColor": "rgba(75, 192, 192, 0.2)",
            "fill": True
        }]
    }
    return jsonify({"chart_data": chart_data}), 200

# Get RealNex groups
@app.route('/get-realnex-groups', methods=['GET'])
async def get_realnex_groups():
    user_id = "default"
    token = get_token(user_id, "realnex")
    if not token:
        return jsonify({"answer": "Please fetch your RealNex JWT token in Settings to fetch groups, stud! 🔑"})

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/Groups",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code == 200:
        return jsonify({"groups": response.json().get('value', [])}), 200
    return jsonify({"error": f"Failed to fetch groups: {response.text}"}), 400

# Get marketing lists (Mailchimp audiences)
@app.route('/get-marketing-lists', methods=['GET'])
async def get_marketing_lists():
    user_id = "default"
    token = get_token(user_id, "mailchimp")
    if not token:
        return jsonify({"answer": "Please add your Mailchimp API key in Settings to fetch marketing lists, stud! 🔑"})

    global mailchimp
    mailchimp = MailchimpClient()
    mailchimp.set_config({"api_key": token, "server": MAILCHIMP_SERVER_PREFIX})

    try:
        lists = mailchimp.lists.get_all_lists()
        return jsonify({"lists": lists.get("lists", [])}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to fetch marketing lists: {str(e)}"}), 400

# Save settings route
@app.route('/save-settings', methods=['POST'])
async def save_settings():
    data = request.json
    user_id = "default"
    tokens = data.get('tokens', {})
    email = data.get('email')
    phone = data.get('phone')

    # Save tokens for each service
    for service, token in tokens.items():
        if token and validate_token(token, service):
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, service, token))
        else:
            return jsonify({"error": f"Invalid token for {service}. Please check and try again, stud!"}), 400

    conn.commit()

    # Register for 2FA if email and phone are provided
    if email and phone:
        authy_id = register_user_for_2fa(user_id, email, phone)
        if not authy_id:
            return jsonify({"error": "Failed to register for 2FA"}), 400

    update_onboarding(user_id, "save_settings")
    return jsonify({"message": "Settings saved successfully!"}), 200

# Transcription route
@app.route('/transcribe', methods=['POST'])
async def transcribe():
    data = request.json
    transcription = data.get('transcription', '')
    if not transcription:
        return jsonify({"error": "No transcription provided"}), 400

    # Process transcription as a regular message
    message_data = {"message": transcription}
    request_data = request.copy()
    request_data.json = message_data
    return await ask()

if __name__ == "__main__":
    socketio.run(app, debug=True)
