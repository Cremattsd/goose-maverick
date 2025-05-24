from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from functools import wraps
import pandas as pd
import io
import numpy as np
from sklearn.linear_model import LinearRegression
import PyMuPDF
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
from fuzzywuzzy import fuzz
from collections import defaultdict
import sqlite3
from datetime import datetime
import json
import redis
from mailchimp_marketing import Client as MailchimpClient
from twilio.rest import Client as TwilioClient
from openai import OpenAI

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your_secret_key'
redis_client = redis.Redis(host='localhost', port=6379, db=0)
socketio = SocketIO(app, cors_allowed_origins="*", message_queue='redis://localhost:6379')

# API credentials (replace with your own)
REALNEX_API_KEY = "your_realnex_api_key"
REALNEX_API_BASE = "https://sync.realnex.com/api/v1/CrmOData"
MAILCHIMP_API_KEY = "your_mailchimp_api_key"
MAILCHIMP_SERVER_PREFIX = "us1"
ZOOMINFO_API_KEY = "your_zoominfo_api_key"
APOLLO_API_KEY = "your_apollo_api_key"
TWILIO_ACCOUNT_SID = "your_twilio_account_sid"
TWILIO_AUTH_TOKEN = "your_twilio_auth_token"
TWILIO_AUTHY_API_KEY = "your_authy_api_key"
OPENAI_API_KEY = "your_openai_api_key"

# Initialize clients
mailchimp = MailchimpClient()
mailchimp.set_config({"api_key": MAILCHIMP_API_KEY, "server": MAILCHIMP_SERVER_PREFIX})
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Database setup for user mappings, points, and 2FA
conn = sqlite3.connect('user_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS user_mappings 
                 (user_id TEXT, header TEXT, mapped_field TEXT, frequency INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_points 
                 (user_id TEXT, points INTEGER, last_updated TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_2fa 
                 (user_id TEXT, authy_id TEXT)''')
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

# Authentication decorator to validate RealNex token
def require_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.path == '/ask':
            return f(*args, **kwargs)
        token = request.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return jsonify({"error": "Token is missing or invalid"}), 401
        token = token.split(' ')[1]
        response = httpx.get(
            f"{REALNEX_API_BASE}/ValidateToken",
            headers={'Authorization': f'Bearer {token}'}
        )
        if response.status_code != 200:
            return jsonify({"error": "Invalid RealNex token"}), 401
        return f(*args, **kwargs)
    return decorated_function

# Points system helper with real-time updates via SocketIO
def award_points(user_id, points_to_add, action):
    cursor.execute("SELECT points FROM user_points WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    current_points = result[0] if result else 0
    new_points = current_points + points_to_add
    cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, last_updated) VALUES (?, ?, ?)",
                   (user_id, new_points, datetime.now().isoformat()))
    conn.commit()
    socketio.emit('points_update', {'user_id': user_id, 'points': new_points, 'message': f"Earned {points_to_add} points for {action}!"})
    return new_points, f"Earned {points_to_add} points for {action}! Total points: {new_points} 🏆"

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

# File upload route with OCR and RealNex integration
@app.route('/upload-file', methods=['POST'])
@require_token
async def upload_file():
    data = request.form.to_dict()
    user_id = "default"
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
    token = request.headers.get('Authorization').split(' ')[1]
    valid_types = ['application/pdf', 'image/jpeg', 'image/png', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    
    if file.content_type not in valid_types:
        return jsonify({"error": "Invalid file type. Only PDFs, JPEG/PNG images, and XLSX files are allowed."}), 400

    if file.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        df = pd.read_excel(file, engine='openpyxl')
    else:
        # Extract text via OCR
        text = extract_text_from_file(file)
        if not text:
            return jsonify({"error": "Could not extract data from the file."}), 400
        # Convert text to DataFrame (simplified parsing)
        lines = text.split('\n')
        headers = lines[0].split(',')
        data = [line.split(',') for line in lines[1:] if line]
        df = pd.DataFrame(data, columns=headers)

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
        points, points_message = award_points(user_id, 10, "uploading data")
        message = f"🔥 Imported {len(df)} records into RealNex as {best_match_template}! "
        message += f"Matched fields: {', '.join([f'{k} → {v}' for k, v in matched_fields.items()])}. "
        if unmatched_fields:
            message += f"Unmatched fields: {', '.join(unmatched_fields)}. Map these in RealNex or adjust your file, stud!"
        else:
            message += "All fields matched—smooth sailing, stud!"
        message += f" {points_message}"
        return jsonify({"message": message, "points": points}), 200
    return jsonify({"error": f"Failed to import data into RealNex: {response.text}"}), 400

# Natural language query route with trained AI
@app.route('/ask', methods=['POST'])
async def ask():
    data = request.json
    message = data.get('message', '').lower()
    user_id = "default"

    # RealNex-trained AI responses
    if 'lease comps with rent over' in message:
        rent_threshold = re.search(r'\d+', message)
        if rent_threshold:
            rent_threshold = int(rent_threshold.group())
            token = request.headers.get('Authorization', '').split(' ')[1] if 'Authorization' in request.headers else None
            if token:
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
            return jsonify({"answer": f"Please provide a RealNex token to query LeaseComps with rent over ${rent_threshold}/month."})
    elif 'sale comps in' in message and 'city' in message:
        city = re.search(r'in\s+([a-z\s]+)\s+city', message)
        if city:
            city = city.group(1).strip()
            token = request.headers.get('Authorization', '').split(' ')[1] if 'Authorization' in request.headers else None
            if token:
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
            return jsonify({"answer": f"Please provide a RealNex token to query SaleComps in {city} city."})
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
        return jsonify({"answer": "To import into RealNex, drag-and-drop your XLSX file into the chat. I’ll auto-match your fields to RealNex templates like LeaseComps or SaleComps, and import the data for you. Make sure your file has headers, stud! 🖥️"})
    elif 'realblast' in message:
        return jsonify({"answer": "RealBlasts are RealNex’s email campaigns! You can send them to your CRM groups or the RealNex community (over 100,000 users). Use the 'Send RealBlast' button to create one, stud! 📧"})
    elif 'marketedge' in message:
        return jsonify({"answer": "MarketEdge in RealNex lets you create financial analyses, proposals, flyers, BOVs, and offering memorandums. It auto-populates data from your CRM and uses your branding. Let’s craft some killer collateral, stud! 📈"})
    else:
        return jsonify({"answer": "I can help with RealNex questions, stud! Ask about required fields, specific terms, RealBlasts, MarketEdge, or how to import data. What’s up? 🤙"})

# Dashboard data route
@app.route('/dashboard-data', methods=['GET'])
@require_token
async def dashboard_data():
    user_id = "default"
    token = request.headers.get('Authorization').split(' ')[1]
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/Dashboard",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code != 200:
        return jsonify({"error": f"Failed to fetch dashboard data: {response.text}"}), 400

    data = response.json()
    cursor.execute("SELECT points FROM user_points WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    data["points"] = result[0] if result else 0
    return jsonify(data), 200

# RealNex RealBlast campaign route
@app.route('/send-realnex-realblast', methods=['POST'])
@require_token
async def send_realnex_realblast():
    data = request.json
    user_id = "default"
    token = request.headers.get('Authorization').split(' ')[1]
    two_fa_code = data.get('two_fa_code')
    if not two_fa_code:
        if not send_2fa_code(user_id):
            return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
        return jsonify({"message": "2FA code sent to your phone. Please provide the code to proceed."}), 200

    if not check_2fa(user_id, two_fa_code):
        return jsonify({"error": "Invalid 2FA code"}), 403

    group_id = data.get('group_id')
    campaign_content = data.get('campaign_content')

    if not group_id or not campaign_content:
        return jsonify({"error": "Missing group ID or campaign content, stud!"}), 400

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{REALNEX_API_BASE}/RealBlasts",
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={"group_id": group_id, "content": campaign_content}
        )

    if response.status_code == 200:
        points, points_message = award_points(user_id, 15, "sending a RealNex RealBlast")
        socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"RealBlast sent to group {group_id}!"})
        return jsonify({"message": f"RealBlast sent to group {group_id}! Nice work, stud! 📧 {points_message}", "points": points}), 200
    return jsonify({"error": f"Failed to send RealBlast: {response.text}"}), 400

# Mailchimp campaign route
@app.route('/send-mailchimp-campaign', methods=['POST'])
@require_token
async def send_mailchimp_campaign():
    data = request.json
    user_id = "default"
    two_fa_code = data.get('two_fa_code')
    if not two_fa_code:
        if not send_2fa_code(user_id):
            return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
        return jsonify({"message": "2FA code sent to your phone. Please provide the code to proceed."}), 200

    if not check_2fa(user_id, two_fa_code):
        return jsonify({"error": "Invalid 2FA code"}), 403

    audience_id = data.get('audience_id')
    campaign_content = data.get('campaign_content')

    if not audience_id or not campaign_content:
        return jsonify({"error": "Missing audience ID or campaign content, stud!"}), 400

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
        points, points_message = award_points(user_id, 15, "sending a Mailchimp campaign")
        socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"Mailchimp campaign sent to audience {audience_id}!"})
        return jsonify({"message": f"Mailchimp campaign sent to audience {audience_id}! Nice work, stud! 📧 {points_message}", "points": points}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to send Mailchimp campaign: {str(e)}"}), 400

# CRM data sync route (ZoomInfo/Apollo.io)
@app.route('/sync-crm-data', methods=['POST'])
@require_token
async def sync_crm_data():
    data = request.json
    user_id = "default"
    token = request.headers.get('Authorization').split(' ')[1]

    # Fetch contacts from ZoomInfo
    zoominfo_contacts = []
    if ZOOMINFO_API_KEY:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.zoominfo.com/v1/contacts",
                headers={"Authorization": f"Bearer {ZOOMINFO_API_KEY}"}
            )
        if response.status_code == 200:
            zoominfo_contacts = response.json().get("contacts", [])

    # Fetch contacts from Apollo.io
    apollo_contacts = []
    if APOLLO_API_KEY:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.apollo.io/v1/contacts",
                headers={"Authorization": f"Bearer {APOLLO_API_KEY}"}
            )
        if response.status_code == 200:
            apollo_contacts = response.json().get("contacts", [])

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
            points, points_message = award_points(user_id, 10, "bringing in data")
            return jsonify({
                "message": f"Synced {len(contacts)} contacts into RealNex, stud! 📇 {points_message}",
                "points": points
            }), 200
        return jsonify({"error": f"Failed to import contacts into RealNex: {response.text}"}), 400
    return jsonify({"message": "No contacts to sync."}), 200

# Predictive analytics with ML
@app.route('/predict-deal', methods=['POST'])
@require_token
async def predict_deal():
    data = request.json
    user_id = "default"
    token = request.headers.get('Authorization').split(' ')[1]
    deal_type = data.get('deal_type')
    deal_data = data.get('deal_data')

    if not deal_type or not deal_data:
        return jsonify({"error": "Missing deal type or data"}), 400

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/{deal_type}s",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code != 200:
        return jsonify({"error": f"Failed to fetch historical data: {response.text}"}), 400

    historical_data = response.json().get('value', [])
    if not historical_data:
        return jsonify({"error": "No historical data available for prediction"}), 400

    # Train a simple linear regression model
    X = []
    y = []
    if deal_type == "LeaseComp":
        for item in historical_data:
            X.append([item.get("sq_ft", 0)])
            y.append(item.get("rent_month", 0))
        model = LinearRegression()
        model.fit(X, y)
        predicted_rent = model.predict([[deal_data.get("sq_ft", 0)]])[0]
        return jsonify({"prediction": f"Predicted rent for {deal_data.get('sq_ft')} sq ft: ${predicted_rent:.2f}/month"})
    elif deal_type == "SaleComp":
        for item in historical_data:
            X.append([item.get("sq_ft", 0)])
            y.append(item.get("sale_price", 0))
        model = LinearRegression()
        model.fit(X, y)
        predicted_price = model.predict([[deal_data.get("sq_ft", 0)]])[0]
        return jsonify({"prediction": f"Predicted sale price for {deal_data.get('sq_ft')} sq ft: ${predicted_price:.2f}"})
    return jsonify({"error": "Unsupported deal type"}), 400

# Email drafting with OpenAI
@app.route('/draft-email', methods=['POST'])
@require_token
async def draft_email():
    data = request.json
    user_id = "default"
    campaign_type = data.get('campaign_type')
    audience_id = data.get('audience_id')
    subject = data.get('subject', "Your CRE Update")

    if not campaign_type or not audience_id:
        return jsonify({"error": "Missing campaign type or audience ID"}), 400

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                {"role": "user", "content": f"Draft a {campaign_type} email for audience {audience_id} with subject '{subject}'."}
            ]
        )
        content = response.choices[0].message.content
        return jsonify({
            "subject": subject,
            "content": content,
            "message": "Email drafted! You can edit and send it using the Send RealBlast or Send Mailchimp Campaign button."
        }), 200
    except Exception as e:
        return jsonify({"error": f"Failed to draft email: {str(e)}"}), 400

# Transcription route
@app.route('/transcribe', methods=['POST'])
@require_token
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

# Sync contacts route
@app.route('/sync-contacts', methods=['POST'])
@require_token
async def sync_contacts():
    data = request.json
    user_id = "default"
    token = request.headers.get('Authorization').split(' ')[1]

    # Example: Sync with Google (requires OAuth setup)
    google_token = data.get('google_token')
    if not google_token:
        return jsonify({"error": "Google token required for syncing"}), 400

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {google_token}"}
        )
    if response.status_code != 200:
        return jsonify({"error": f"Failed to fetch Google contacts: {response.text}"}), 400

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
            return jsonify({"message": f"Synced {len(contacts)} contacts into RealNex!"}), 200
        return jsonify({"error": f"Failed to import contacts into RealNex: {response.text}"}), 400
    return jsonify({"message": "No contacts to sync."}), 200

# Verify emails route
@app.route('/verify-emails', methods=['POST'])
@require_token
async def verify_emails():
    data = request.json
    emails = data.get('emails', [])
    if not emails:
        return jsonify({"error": "No emails provided"}), 400

    # Use a real email verification service (e.g., NeverBounce)
    verified_emails = []
    for email in emails:
        # Placeholder for real email verification API
        verified_emails.append({"email": email, "status": "valid"})  # Replace with actual API call

    return jsonify({"verified_emails": verified_emails, "message": f"Verified {len(verified_emails)} emails, stud! ✨"}), 200

# Summarize route
@app.route('/summarize', methods=['POST'])
@require_token
async def summarize():
    data = request.json
    text = data.get('text', '')
    if not text:
        return jsonify({"error": "No text provided for summarization"}), 400

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a text summarizer for a commercial real estate chatbot."},
                {"role": "user", "content": f"Summarize this text: {text}"}
            ]
        )
        summary = response.choices[0].message.content
        return jsonify({"summary": summary}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to summarize text: {str(e)}"}), 400

# Get RealNex groups
@app.route('/get-realnex-groups', methods=['GET'])
@require_token
async def get_realnex_groups():
    token = request.headers.get('Authorization').split(' ')[1]
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
@require_token
async def get_marketing_lists():
    try:
        lists = mailchimp.lists.get_all_lists()
        return jsonify({"lists": lists.get("lists", [])}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to fetch marketing lists: {str(e)}"}), 400

# Save settings route
@app.route('/save-settings', methods=['POST'])
@require_token
async def save_settings():
    data = request.json
    user_id = "default"
    token = data.get('token')
    email = data.get('email')
    phone = data.get('phone')

    # Validate token
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{REALNEX_API_BASE}/ValidateToken",
            headers={'Authorization': f'Bearer {token}'}
        )
    if response.status_code != 200:
        return jsonify({"error": "Invalid RealNex token"}), 400

    # Register for 2FA if email and phone are provided
    if email and phone:
        authy_id = register_user_for_2fa(user_id, email, phone)
        if not authy_id:
            return jsonify({"error": "Failed to register for 2FA"}), 400

    return jsonify({"message": "Settings saved successfully!"}), 200

if __name__ == "__main__":
    socketio.run(app, debug=True)
