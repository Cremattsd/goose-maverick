import os
import json
import logging
import redis
import jwt
import httpx
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from flask_socketio import SocketIO, join_room
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fpdf import FPDF
from io import BytesIO
import commands
import utils
import pandas as pd
import pytesseract
from PIL import Image
import PyPDF2
import cmd_sync_data
from functools import wraps

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
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Create uploads directory
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Redis setup
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

# Create tables
cursor.execute('''CREATE TABLE IF NOT EXISTS user_points
                  (user_id TEXT PRIMARY KEY, points INTEGER, email_credits INTEGER, has_msa INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings
                  (user_id TEXT PRIMARY KEY, language TEXT, subject_generator_enabled INTEGER, 
                   deal_alerts_enabled INTEGER, email_notifications INTEGER, sms_notifications INTEGER,
                   mailchimp_group_id TEXT, constant_contact_group_id TEXT, realnex_group_id TEXT,
                   apollo_group_id TEXT, seamless_group_id TEXT, zoominfo_group_id TEXT)''')
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
                  phone TEXT,
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
cursor.execute('''CREATE TABLE IF NOT EXISTS health_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  contact_id TEXT,
                  email_health_score INTEGER,
                  phone_health_score INTEGER,
                  timestamp TIMESTAMP)''')
conn.commit()

# JWT Token Required Decorator
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"error": "Token is missing—don’t ghost me like an unsigned lease! 👻"}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            user_id = data.get('user_id', 'default')
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired—faster than a hot property listing! ⏰"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token—try again, champ! 🔐"}), 401
        return f(user_id, *args, **kwargs)
    return decorated_function

# Helper function for PDF reports
def generate_pdf_report(user_id, data, report_title):
    """Generate a PDF report from given data—like a CRE report that seals the deal! 📜"""
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
    """Health check endpoint for Render to detect the app—keeping it alive like a thriving CRE market! 🏙️"""
    return jsonify({"status": "healthy"})

@app.route('/', methods=['GET'])
@token_required
def index(user_id):
    logger.info("Redirecting to chat hub—like a CRE agent pointing you to the best property! 🏢")
    return redirect(url_for('chat_hub'))

@app.route('/chat-hub', methods=['GET'])
@token_required
def chat_hub(user_id):
    logger.info("Chat hub page accessed—time to talk CRE deals! 💬")
    return render_template('index.html')

@app.route('/dashboard', methods=['GET'])
@token_required
def dashboard(user_id):
    logger.info("Duplicates dashboard page accessed—let’s clean up like a pro property manager! 🧹")
    return render_template('duplicates_dashboard.html')

@app.route('/activity', methods=['GET'])
@token_required
def activity(user_id):
    logger.info("Activity log page accessed—tracking moves smoother than a CRE deal closing!")
    return render_template('activity.html')

@app.route('/deal-trends', methods=['GET'])
@token_required
def deal_trends(user_id):
    logger.info("Deal trends page accessed—let’s analyze the market like CRE pros! 📈")
    current_date = datetime.now().isoformat()
    historical_data = [
        {"sq_ft": 1000, "rent_month": 2000, "sale_price": 500000, "deal_type": "LeaseComp", "date": current_date},
        {"sq_ft": 2000, "rent_month": 3500, "sale_price": 750000, "deal_type": "LeaseComp", "date": current_date},
        {"sq_ft": 3000, "rent_month": 5000, "sale_price": 1000000, "deal_type": "SaleComp", "date": current_date},
        {"sq_ft": 4000, "rent_month": 6500, "sale_price": 1200000, "deal_type": "SaleComp", "date": current_date}
    ]
    lease_data = [item for item in historical_data if item["deal_type"] == "LeaseComp"]
    sale_data = [item for item in historical_data if item["deal_type"] == "SaleComp"]
    return render_template('deal_trends.html', lease_data=lease_data, sale_data=sale_data)

@app.route('/field-map', methods=['GET'])
@token_required
def field_map(user_id):
    logger.info("Field mapping editor page accessed—mapping fields like a CRE blueprint! 🗺️")
    return render_template('field_map.html')

@app.route('/ocr', methods=['GET'])
@token_required
def ocr_page(user_id):
    logger.info("OCR scanner page accessed—scanning docs faster than a CRE agent on a deadline! 📄")
    return render_template('ocr.html')

@app.route('/upload-file', methods=['POST'])
@token_required
def upload_file(user_id):
    if 'file' not in request.files:
        return jsonify({"error": "No file part—don’t leave me empty-handed like an unleased space! 🏢"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file—pick one, let’s make a deal! 📂"}), 400

    # Securely save the file
    filename = file.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Fetch users for logging
    import asyncio
    users = asyncio.run(utils.get_users(user_id, cursor))
    user_name = "Unknown"
    if users:
        for user in users:
            if user.get("userId") == user_id:
                user_name = user.get("userName", "Unknown")
                break

    # Determine file type and process
    try:
        if filename.endswith('.xlsx'):
            # Process XLSX
            df = pd.read_excel(file_path)
            contacts = []
            companies = []
            properties = []
            spaces = []
            projects = []
            leasecomps = []
            salecomps = []
            events = []
            history_entries = []

            # Map XLSX columns to RealNex entities
            for _, row in df.iterrows():
                # Contact
                if 'Full Name' in row or 'Email' in row:
                    full_name = str(row.get('Full Name', ''))
                    contact = {
                        "Full Name": full_name,
                        "Email": str(row.get('Email', '')),
                        "Phone": str(row.get('Phone', '')),
                        "Address": str(row.get('Address', '')),
                        "City": str(row.get('City', '')),
                        "State": str(row.get('State', '')),
                        "Zip": str(row.get('Zip', '')),
                        "Prospect": bool(row.get('Prospect', True)),
                        "Investor": bool(row.get('Investor', False))
                    }
                    contacts.append(contact)

                # Company
                if 'Company Name' in row:
                    company = {
                        "Name": str(row.get('Company Name', '')),
                        "Address": str(row.get('Address', '')),
                        "City": str(row.get('City', '')),
                        "State": str(row.get('State', '')),
                        "Zip": str(row.get('Zip', '')),
                        "Email": str(row.get('Email', '')),
                        "Phone": str(row.get('Phone', '')),
                        "Prospect": bool(row.get('Prospect', True))
                    }
                    companies.append(company)

                # Property
                if 'Property Name' in row:
                    property = {
                        "Name": str(row.get('Property Name', '')),
                        "Address": str(row.get('Address', '')),
                        "City": str(row.get('City', '')),
                        "State": str(row.get('State', '')),
                        "Zip": str(row.get('Zip', '')),
                        "For Sale": bool(row.get('For Sale', False)),
                        "For Lease": bool(row.get('For Lease', False)),
                        "Owner Occupied": bool(row.get('Owner Occupied', False)),
                        "Square Feet": float(row.get('Square Feet', 0)),
                        "id": f"prop_{len(properties)}_{user_id}"
                    }
                    properties.append(property)

                # Space
                if 'Space Number' in row and properties:
                    space = {
                        "Property ID": properties[-1]["id"],
                        "Suite": str(row.get('Space Number', '')),
                        "Is Available": bool(row.get('Is Available', True)),
                        "Is Office": bool(row.get('Is Office', False))
                    }
                    spaces.append(space)

                # Project
                if 'Project Name' in row:
                    project = {
                        "Project": str(row.get('Project Name', '')),
                        "Status": str(row.get('Project Status', 'Open')),
                        "Date Opened": datetime.now().isoformat()
                    }
                    projects.append(project)

                # LeaseComp
                if 'Lease Suite' in row and properties:
                    leasecomp = {
                        "Suite": str(row.get('Lease Suite', '')),
                        "Property Name": properties[-1]["Name"] if properties else "Unknown Property",
                        "Deal Date": datetime.now().isoformat(),
                        "Lease Commencement": datetime.now().isoformat(),
                        "Lease Expiry": datetime.now().isoformat()
                    }
                    leasecomps.append(leasecomp)

                # SaleComp
                if 'Sale Property' in row:
                    salecomp = {
                        "Property Name": str(row.get('Sale Property', '')),
                        "Sale Date": datetime.now().isoformat(),
                        "Sale Price": float(row.get('Sale Price', 0))
                    }
                    salecomps.append(salecomp)

                # Event
                if 'Meeting Subject' in row:
                    event = {
                        "Subject": str(row.get('Meeting Subject', '')),
                        "Start Date": datetime.now().isoformat(),
                        "End Date": (datetime.now() + timedelta(hours=1)).isoformat()
                    }
                    events.append(event)

                # History
                if 'History' in row:
                    history_text = str(row.get('History', ''))
                    # Parse history like "Matthew Smith 'History: Matt is good at jokes'"
                    try:
                        if 'History:' in history_text:
                            parts = history_text.split('History:', 1)
                            contact_name = parts[0].strip()
                            history_note = parts[1].strip()
                            nickname = history_note.split(' ')[0] if history_note else contact_name.split(' ')[0]
                            history_entries.append({
                                "contact_name": contact_name,
                                "nickname": nickname,
                                "history_note": history_note
                            })
                    except Exception as e:
                        logger.error(f"Failed to parse history entry '{history_text}': {e}")

            # Process entities
            realnex_token = utils.get_token(user_id, "realnex", cursor)
            realnex_group_id = utils.get_user_settings(user_id, cursor, conn).get("realnex_group_id")
            if not realnex_token or not realnex_group_id:
                return jsonify({"error": "RealNex token or group ID missing—can’t sync without the keys to the building! 🔑"}), 401

            # Process contacts
            synced_contacts = []
            for contact in contacts:
                contact_hash = utils.hash_entity(contact, "contact")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                               (user_id, contact_hash))
                if cursor.fetchone():
                    utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                    continue

                # Search RealNex to avoid duplicates
                email = contact.get('Email', '')
                full_name = contact.get('Full Name', '')
                if email or full_name:
                    query_params = {"$filter": f"email eq '{email}'" if email else f"fullName eq '{full_name}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "contact", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                        continue

                # Split Full Name into First and Last Name
                full_name = contact.get('Full Name', '')
                first_name = full_name.split(' ')[0] if full_name else ''
                last_name = ' '.join(full_name.split(' ')[1:]) if len(full_name.split(' ')) > 1 else ''

                contact_data = {
                    "id": f"contact_{len(synced_contacts)}_{user_id}",
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": contact.get('Email', ''),
                    "mobile": contact.get('Phone', ''),
                    "address": {
                        "address1": contact.get('Address', ''),
                        "city": contact.get('City', ''),
                        "state": contact.get('State', ''),
                        "zipCode": contact.get('Zip', ''),
                        "country": "USA"
                    },
                    "prospect": contact.get('Prospect', True),
                    "investor": contact.get('Investor', False)
                }
                try:
                    with httpx.Client() as client:
                        response = client.post(
                            "https://sync.realnex.com/api/v1/Crm/contact",
                            headers={'Authorization': f'Bearer {realnex_token}'},
                            json={
                                "firstName": contact_data["firstName"],
                                "lastName": contact_data["lastName"],
                                "email": contact_data["email"],
                                "mobile": contact_data["mobile"],
                                "address": contact_data["address"],
                                "prospect": contact_data["prospect"],
                                "investor": contact_data["investor"],
                                "doNotEmail": False,
                                "doNotCall": False,
                                "doNotFax": False,
                                "doNotMail": False,
                                "objectGroups": [{"key": realnex_group_id}],
                                "source": "CRE Chat Bot"
                            }
                        )
                        response.raise_for_status()
                        contact_response = response.json()
                        contact_key = contact_response.get("key", contact_data["id"])
                        contact_data["id"] = contact_key
                        email_score = cmd_sync_data.check_email_health(contact_data["email"]) if contact_data["email"] else 0
                        phone_score = cmd_sync_data.check_phone_health(contact_data["mobile"]) if contact_data["mobile"] else 0
                        utils.log_health_history(user_id, contact_data["id"], email_score, phone_score, cursor, conn)
                        cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                       (contact_data["id"], full_name, contact_data["email"], contact_data["mobile"], user_id))
                        conn.commit()
                        utils.log_change(user_id, "contact", contact_data["id"], "created", {"firstName": contact_data["firstName"], "lastName": contact_data["lastName"], "changed_by": user_name}, cursor, conn)
                        synced_contacts.append(contact_data)
                        # Sync history to RealNex
                        asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                except Exception as e:
                    logger.error(f"Failed to create contact {contact_data['id']} in RealNex: {e}")
                    return jsonify({"error": f"Failed to create contact: {str(e)}"}), 500

            # Process companies
            synced_companies = []
            for company in companies:
                company_data = {
                    "id": f"company_{len(synced_companies)}_{user_id}",
                    "organizationId": company.get("Name", ""),
                    "address": {
                        "address1": company.get("Address", ""),
                        "city": company.get("City", ""),
                        "state": company.get("State", ""),
                        "zipCode": company.get("Zip", ""),
                        "country": "USA"
                    },
                    "email": company.get("Email", ""),
                    "phone": company.get("Phone", ""),
                    "prospect": company.get("Prospect", True)
                }
                company_hash = utils.hash_entity(company_data, "company")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, company_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"organizationId eq '{company_data['organizationId']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "company", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, company_data, "company", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/company",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "organizationId": company_data["organizationId"],
                                    "address": company_data["address"],
                                    "email": company_data["email"],
                                    "phone": company_data["phone"],
                                    "prospect": company_data["prospect"],
                                    "doNotEmail": False,
                                    "doNotCall": False,
                                    "doNotFax": False,
                                    "doNotMail": False,
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            company_response = response.json()
                            company_key = company_response.get("key", company_data["id"])
                            company_data["id"] = company_key
                            synced_companies.append(company_data)
                            utils.log_user_activity(user_id, "sync_realnex_company", {"company_id": company_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "company", company_data["id"], "created", {"organizationId": company_data["organizationId"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync company {company_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync company: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, company_data, "company", cursor, conn)

            # Process properties
            synced_properties = []
            for prop in properties:
                prop_data = {
                    "id": prop["id"],
                    "propertyName": prop.get("Name", ""),
                    "address": {
                        "address1": prop.get("Address", ""),
                        "city": prop.get("City", ""),
                        "state": prop.get("State", ""),
                        "zipCode": prop.get("Zip", ""),
                        "country": "USA"
                    },
                    "forSale": prop.get("For Sale", False),
                    "forLease": prop.get("For Lease", False),
                    "ownerOccupied": prop.get("Owner Occupied", False),
                    "sqft": prop.get("Square Feet", 0)
                }
                prop_hash = utils.hash_entity(prop_data, "property")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, prop_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"propertyName eq '{prop_data['propertyName']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "property", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, prop_data, "property", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/property",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "propertyName": prop_data["propertyName"],
                                    "address": prop_data["address"],
                                    "forSale": prop_data["forSale"],
                                    "forLease": prop_data["forLease"],
                                    "ownerOccupied": prop_data["ownerOccupied"],
                                    "sqft": prop_data["sqft"],
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            prop_response = response.json()
                            prop_key = prop_response.get("key", prop_data["id"])
                            prop_data["id"] = prop_key
                            synced_properties.append(prop_data)
                            utils.log_user_activity(user_id, "sync_realnex_property", {"property_id": prop_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "property", prop_data["id"], "created", {"propertyName": prop_data["propertyName"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync property {prop_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync property: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, prop_data, "property", cursor, conn)

            # Process spaces
            synced_spaces = []
            for space in spaces:
                space_data = {
                    "id": f"space_{len(synced_spaces)}_{user_id}",
                    "crm_property_key": space["Property ID"],
                    "suite": space["Suite"],
                    "isAvailable": space["Is Available"],
                    "isOffice": space["Is Office"]
                }
                space_hash = utils.hash_entity(space_data, "space")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, space_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"suite eq '{space_data['suite']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "space", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, space_data, "space", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                f"https://sync.realnex.com/api/v1/Crm/property/{space_data['crm_property_key']}/space",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "suite": space_data["suite"],
                                    "isAvailable": space_data["isAvailable"],
                                    "isRetail": False,
                                    "isVacant": False,
                                    "isIndustrial": False,
                                    "isOffice": space_data["isOffice"],
                                    "isSublease": False,
                                    "isOther": False,
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            space_response = response.json()
                            space_key = space_response.get("key", space_data["id"])
                            space_data["id"] = space_key
                            synced_spaces.append(space_data)
                            utils.log_user_activity(user_id, "sync_realnex_space", {"space_id": space_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "space", space_data["id"], "created", {"suite": space_data["suite"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync space {space_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync space: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, space_data, "space", cursor, conn)

            # Process projects
            synced_projects = []
            for project in projects:
                project_data = {
                    "id": f"project_{len(synced_projects)}_{user_id}",
                    "project": project["Project"],
                    "projectStatus": project["Status"],
                    "dateOpened": project["Date Opened"]
                }
                project_hash = utils.hash_entity(project_data, "project")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, project_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"project eq '{project_data['project']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "project", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, project_data, "project", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/project",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "project": project_data["project"],
                                    "projectStatus": project_data["projectStatus"],
                                    "dateOpened": project_data["dateOpened"],
                                    "investment": False,
                                    "inhouselisting": False,
                                    "inhouserepresentation": False,
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            project_response = response.json()
                            project_key = project_response.get("key", project_data["id"])
                            project_data["id"] = project_key
                            synced_projects.append(project_data)
                            utils.log_user_activity(user_id, "sync_realnex_project", {"project_id": project_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "project", project_data["id"], "created", {"project": project_data["project"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync project {project_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync project: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, project_data, "project", cursor, conn)

            # Process leasecomps
            synced_leasecomps = []
            for leasecomp in leasecomps:
                leasecomp_data = {
                    "id": f"leasecomp_{len(synced_leasecomps)}_{user_id}",
                    "suite": leasecomp["Suite"],
                    "propertyName": leasecomp["Property Name"],
                    "dealDate": leasecomp["Deal Date"],
                    "leaseCommencement": leasecomp["Lease Commencement"],
                    "leaseExpiry": leasecomp["Lease Expiry"]
                }
                leasecomp_hash = utils.hash_entity(leasecomp_data, "leasecomp")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, leasecomp_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"suite eq '{leasecomp_data['suite']}' and propertyName eq '{leasecomp_data['propertyName']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "leasecomp", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, leasecomp_data, "leasecomp", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/leasecomp",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "suite": leasecomp_data["suite"],
                                    "propertyName": leasecomp_data["propertyName"],
                                    "details": {
                                        "dealDate": leasecomp_data["dealDate"],
                                        "leaseCommencement": leasecomp_data["leaseCommencement"],
                                        "leaseExpiry": leasecomp_data["leaseExpiry"],
                                        "office": False,
                                        "retail": False,
                                        "industrial": False,
                                        "other": False
                                    },
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            leasecomp_response = response.json()
                            leasecomp_key = leasecomp_response.get("key", leasecomp_data["id"])
                            leasecomp_data["id"] = leasecomp_key
                            synced_leasecomps.append(leasecomp_data)
                            utils.log_user_activity(user_id, "sync_realnex_leasecomp", {"leasecomp_id": leasecomp_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "leasecomp", leasecomp_data["id"], "created", {"suite": leasecomp_data["suite"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync leasecomp {leasecomp_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync leasecomp: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, leasecomp_data, "leasecomp", cursor, conn)

            # Process salecomps
            synced_salecomps = []
            for salecomp in salecomps:
                salecomp_data = {
                    "id": f"salecomp_{len(synced_salecomps)}_{user_id}",
                    "propertyName": salecomp["Property Name"],
                    "saleDate": salecomp["Sale Date"],
                    "salePrice": salecomp["Sale Price"]
                }
                salecomp_hash = utils.hash_entity(salecomp_data, "salecomp")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, salecomp_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"propertyName eq '{salecomp_data['propertyName']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "salecomp", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, salecomp_data, "salecomp", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/SaleComp",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "propertyName": salecomp_data["propertyName"],
                                    "details": {
                                        "saleDate": salecomp_data["saleDate"],
                                        "salePrice": salecomp_data["salePrice"]
                                    },
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            salecomp_response = response.json()
                            salecomp_key = salecomp_response.get("key", salecomp_data["id"])
                            salecomp_data["id"] = salecomp_key
                            synced_salecomps.append(salecomp_data)
                            utils.log_user_activity(user_id, "sync_realnex_salecomp", {"salecomp_id": salecomp_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "salecomp", salecomp_data["id"], "created", {"propertyName": salecomp_data["propertyName"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync salecomp {salecomp_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync salecomp: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, salecomp_data, "salecomp", cursor, conn)

            # Process events
            synced_events = []
            for event in events:
                event_data = {
                    "id": f"event_{len(synced_events)}_{user_id}",
                    "subject": event["Subject"],
                    "startDate": event["Start Date"],
                    "endDate": event["End Date"]
                }
                event_hash = utils.hash_entity(event_data, "event")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, event_hash))
                if not cursor.fetchone():
                    # Search RealNex to avoid duplicates
                    query_params = {"$filter": f"subject eq '{event_data['subject']}' and startDate eq '{event_data['startDate']}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "event", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, event_data, "event", cursor, conn)
                        continue

                    try:
                        with httpx.Client() as client:
                            response = client.post(
                                "https://sync.realnex.com/api/v1/Crm/event",
                                headers={'Authorization': f'Bearer {realnex_token}'},
                                json={
                                    "userKey": user_id,
                                    "subject": event_data["subject"],
                                    "startDate": event_data["startDate"],
                                    "endDate": event_data["endDate"],
                                    "timeZone": "UTC",
                                    "timeless": False,
                                    "allDay": False,
                                    "finished": False,
                                    "alarmMinutes": 0,
                                    "eventType": {"key": 1},
                                    "priority": {"key": 1},
                                    "objectGroups": [{"key": realnex_group_id}],
                                    "source": "CRE Chat Bot"
                                }
                            )
                            response.raise_for_status()
                            event_response = response.json()
                            event_key = event_response.get("key", event_data["id"])
                            event_data["id"] = event_key
                            synced_events.append(event_data)
                            utils.log_user_activity(user_id, "sync_realnex_event", {"event_id": event_data["id"], "group_id": realnex_group_id}, cursor, conn)
                            utils.log_change(user_id, "event", event_data["id"], "created", {"subject": event_data["subject"], "changed_by": user_name}, cursor, conn)
                            # Sync history to RealNex
                            asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                    except Exception as e:
                        logger.error(f"Failed to sync event {event_data['id']} to RealNex: {e}")
                        return jsonify({"error": f"Failed to sync event: {str(e)}"}), 500
                else:
                    utils.log_duplicate(user_id, event_data, "event", cursor, conn)

            # Process history entries and create events
            synced_history_events = []
            try:
                for history in history_entries:
                    contact_name = history["contact_name"]
                    nickname = history["nickname"]
                    history_note = history["history_note"]

                    # Search for the contact in RealNex
                    query_params = {"$filter": f"fullName eq '{contact_name}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "contact", query_params, cursor))
                    contact_id = None
                    if search_results and len(search_results) > 0:
                        contact_id = search_results[0]["key"]
                    else:
                        # Create the contact if not found
                        try:
                            first_name = contact_name.split(' ')[0] if contact_name else ''
                            last_name = ' '.join(contact_name.split(' ')[1:]) if len(contact_name.split(' ')) > 1 else ''
                            with httpx.Client() as client:
                                response = client.post(
                                    "https://sync.realnex.com/api/v1/Crm/contact",
                                    headers={'Authorization': f'Bearer {realnex_token}'},
                                    json={
                                        "firstName": first_name,
                                        "lastName": last_name,
                                        "email": "",
                                        "mobile": "",
                                        "address": {"country": "USA"},
                                        "prospect": True,
                                        "investor": False,
                                        "doNotEmail": False,
                                        "doNotCall": False,
                                        "doNotFax": False,
                                        "doNotMail": False,
                                        "objectGroups": [{"key": realnex_group_id}],
                                        "source": "CRE Chat Bot"
                                    }
                                )
                                response.raise_for_status()
                                contact_response = response.json()
                                contact_id = contact_response.get("key")
                                synced_contacts.append({
                                    "id": contact_id,
                                    "firstName": first_name,
                                    "lastName": last_name,
                                    "email": "",
                                    "mobile": ""
                                })
                                cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                               (contact_id, contact_name, "", "", user_id))
                                conn.commit()
                                utils.log_change(user_id, "contact", contact_id, "created", {"firstName": first_name, "lastName": last_name, "changed_by": user_name}, cursor, conn)
                                # Sync history to RealNex
                                asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                        except Exception as e:
                            logger.error(f"Failed to create contact for history entry {contact_name}: {e}")
                            continue

                    # If the history note mentions "jokes," create an event
                    if "jokes" in history_note.lower():
                        event_subject = f"Call {nickname}, ask him a joke"
                        # Determine priority and alarm based on context
                        priority_key = 2 if "urgent" in history_note.lower() else 1  # Higher priority if urgent
                        alarm_minutes = 15 if "urgent" in history_note.lower() else 0  # Reminder 15 minutes before if urgent
                        event_data = {
                            "id": f"event_{len(synced_events) + len(synced_history_events)}_{user_id}",
                            "subject": event_subject,
                            "startDate": datetime.now().isoformat(),
                            "endDate": (datetime.now() + timedelta(minutes=30)).isoformat(),
                            "contact_id": contact_id,
                            "description": f"Note: {history_note}"
                        }
                        event_hash = utils.hash_entity(event_data, "event")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, event_hash))
                        if not cursor.fetchone():
                            # Search RealNex to avoid duplicates
                            query_params = {"$filter": f"subject eq '{event_data['subject']}' and startDate eq '{event_data['startDate']}'"}
                            search_results = asyncio.run(utils.search_realnex_entities(user_id, "event", query_params, cursor))
                            if search_results and len(search_results) > 0:
                                utils.log_duplicate(user_id, event_data, "event", cursor, conn)
                                continue

                            try:
                                with httpx.Client() as client:
                                    response = client.post(
                                        "https://sync.realnex.com/api/v1/Crm/event",
                                        headers={'Authorization': f'Bearer {realnex_token}'},
                                        json={
                                            "userKey": user_id,
                                            "subject": event_data["subject"],
                                            "description": event_data["description"],
                                            "startDate": event_data["startDate"],
                                            "endDate": event_data["endDate"],
                                            "timeZone": "UTC",
                                            "timeless": False,
                                            "allDay": False,
                                            "finished": False,
                                            "alarmMinutes": alarm_minutes,
                                            "eventType": {"key": 1},
                                            "priority": {"key": priority_key},
                                            "eventObjects": [{"type": "contact", "key": contact_id}],
                                            "objectGroups": [{"key": realnex_group_id}],
                                            "source": "CRE Chat Bot"
                                        }
                                    )
                                    response.raise_for_status()
                                    event_response = response.json()
                                    event_key = event_response.get("key", event_data["id"])
                                    event_data["id"] = event_key
                                    synced_history_events.append(event_data)
                                    utils.log_user_activity(user_id, "sync_realnex_event", {"event_id": event_data["id"], "group_id": realnex_group_id}, cursor, conn)
                                    utils.log_change(user_id, "event", event_data["id"], "created", {"subject": event_data["subject"], "changed_by": user_name}, cursor, conn)
                                    # Sync history to RealNex
                                    asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                            except Exception as e:
                                logger.error(f"Failed to create event for history entry {history_note}: {e}")
                                continue
                        else:
                            utils.log_duplicate(user_id, event_data, "event", cursor, conn)
                    else:
                        # Log the history note to RealNex history
                        try:
                            with httpx.Client() as client:
                                history_entry = {
                                    "entityType": "contact",
                                    "entityId": contact_id,
                                    "action": "note_added",
                                    "description": f"History note added for {contact_name}",
                                    "details": {"note": history_note},
                                    "changeDate": datetime.now().isoformat(),
                                    "user": {"userName": user_name}
                                }
                                response = client.post(
                                    "https://sync.realnex.com/api/v1/Crm/history",
                                    headers={'Authorization': f'Bearer {realnex_token}'},
                                    json=history_entry
                                )
                                response.raise_for_status()
                                utils.log_user_activity(user_id, "sync_realnex_history", {"contact_id": contact_id, "note": history_note}, cursor, conn)
                                utils.log_change(user_id, "contact", contact_id, "history_added", {"note": history_note, "changed_by": user_name}, cursor, conn)
                                # Sync history to RealNex
                                asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                        except Exception as e:
                            logger.error(f"Failed to log history note for {contact_name}: {e}")
                            continue
            except Exception as e:
                logger.error(f"Failed to process history entries in XLSX: {e}")
                return jsonify({"error": f"Failed to process history entries: {str(e)}"}), 500

            logger.info(f"XLSX file processed for user {user_id}—synced to RealNex like a pro! 🏢")
            return jsonify({
                "status": "XLSX processed and synced to RealNex—boom, deal done! 💥",
                "contacts": synced_contacts,
                "companies": synced_companies,
                "properties": synced_properties,
                "spaces": synced_spaces,
                "projects": synced_projects,
                "leasecomps": synced_leasecomps,
                "salecomps": synced_salecomps,
                "events": synced_events + synced_history_events
            })

        elif filename.endswith('.pdf'):
            # Fetch field mappings for all entities
            import asyncio
            property_mappings = asyncio.run(utils.get_field_mappings(user_id, "property", cursor))
            space_mappings = asyncio.run(utils.get_field_mappings(user_id, "space", cursor))
            company_mappings = asyncio.run(utils.get_field_mappings(user_id, "company", cursor))
            project_mappings = asyncio.run(utils.get_field_mappings(user_id, "project", cursor))
            leasecomp_mappings = asyncio.run(utils.get_field_mappings(user_id, "leasecomp", cursor))
            salecomp_mappings = asyncio.run(utils.get_field_mappings(user_id, "salecomp", cursor))

            if not all([property_mappings, space_mappings, company_mappings, project_mappings, leasecomp_mappings, salecomp_mappings]):
                return jsonify({"error": "Failed to fetch field mappings from RealNex—need the blueprints to build! 🗺️"}), 500

            # Process PDF for all entities
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"

            # Parse entities using field mappings
            properties = []
            spaces = []
            companies = []
            projects = []
            leasecomps = []
            salecomps = []
            events = []
            history_entries = []
            current_property = None
            current_space = None
            current_company = None
            current_project = None
            current_leasecomp = None
            current_salecomp = None
            current_event = None

            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Match property fields
                if "name" in property_mappings and property_mappings["name"] in line:
                    name = line.replace(property_mappings["name"], "").strip()
                    current_property = {"name": name, "address": "", "city": "", "zip": "", "forSale": False, "forLease": False, "ownerOccupied": False, "sqft": 0, "id": f"prop_{len(properties)}_{user_id}"}
                elif "address" in property_mappings and property_mappings["address"] in line and current_property:
                    current_property["address"] = line.replace(property_mappings["address"], "").strip()
                elif "city" in property_mappings and property_mappings["city"] in line and current_property:
                    current_property["city"] = line.replace(property_mappings["city"], "").strip()
                elif "zip" in property_mappings and property_mappings["zip"] in line and current_property:
                    current_property["zip"] = line.replace(property_mappings["zip"], "").strip()
                elif "For Sale:" in line and current_property:
                    current_property["forSale"] = "True" in line
                elif "For Lease:" in line and current_property:
                    current_property["forLease"] = "True" in line
                elif "Owner Occupied:" in line and current_property:
                    current_property["ownerOccupied"] = "True" in line
                elif "Square Feet:" in line and current_property:
                    try:
                        current_property["sqft"] = float(line.replace("Square Feet:", "").strip())
                    except ValueError:
                        current_property["sqft"] = 0
                    if all([current_property["address"], current_property["city"], current_property["zip"]]):
                        properties.append(current_property)
                        current_property = None

                # Match space fields
                if "space_number" in space_mappings and space_mappings["space_number"] in line:
                    space_number = line.replace(space_mappings["space_number"], "").strip()
                    if properties:
                        space = {
                            "id": f"space_{len(spaces)}_{user_id}",
                            "property_id": properties[-1]["id"],
                            "suite": space_number,
                            "isAvailable": True,
                            "isOffice": False
                        }
                        spaces.append(space)

                # Match company fields
                if "name" in company_mappings and company_mappings["name"] in line:
                    company_name = line.replace(company_mappings["name"], "").strip()
                    current_company = {"name": company_name, "address": "", "email": "", "phone": "", "prospect": True, "id": f"company_{len(companies)}_{user_id}"}
                elif "address" in company_mappings and company_mappings["address"] in line and current_company:
                    current_company["address"] = line.replace(company_mappings["address"], "").strip()
                elif "Email:" in line and current_company:
                    current_company["email"] = line.replace("Email:", "").strip()
                elif "Phone:" in line and current_company:
                    current_company["phone"] = line.replace("Phone:", "").strip()
                    companies.append(current_company)
                    current_company = None

                # Match project fields
                if "project" in project_mappings and project_mappings["project"] in line:
                    project_name = line.replace(project_mappings["project"], "").strip()
                    current_project = {"project": project_name, "status": "Open", "dateOpened": datetime.now().isoformat(), "id": f"project_{len(projects)}_{user_id}"}
                    projects.append(current_project)
                    current_project = None

                # Match leasecomp fields
                if "LeaseComp:" in line:
                    suite = line.replace("LeaseComp:", "").strip()
                    current_leasecomp = {
                        "id": f"leasecomp_{len(leasecomps)}_{user_id}",
                        "suite": suite,
                        "propertyName": properties[-1]["name"] if properties else "Unknown Property",
                        "dealDate": datetime.now().isoformat(),
                        "leaseCommencement": datetime.now().isoformat(),
                        "leaseExpiry": datetime.now().isoformat()
                    }
                    leasecomps.append(current_leasecomp)
                    current_leasecomp = None

                # Match salecomp fields
                if "SaleComp:" in line:
                    property_name = line.replace("SaleComp:", "").strip()
                    current_salecomp = {
                        "id": f"salecomp_{len(salecomps)}_{user_id}",
                        "propertyName": property_name,
                        "saleDate": datetime.now().isoformat(),
                        "salePrice": 0
                    }
                    salecomps.append(current_salecomp)
                    current_salecomp = None

                # Match event fields
                if "Meeting:" in line:
                    subject = line.replace("Meeting:", "").strip()
                    current_event = {
                        "id": f"event_{len(events)}_{user_id}",
                        "subject": subject,
                        "startDate": datetime.now().isoformat(),
                        "endDate": (datetime.now() + timedelta(hours=1)).isoformat()
                    }
                    events.append(current_event)
                    current_event = None

                # Match history fields
                if "History:" in line:
                    history_text = line
                    try:
                        parts = history_text.split('History:', 1)
                        contact_name = parts[0].strip()
                        history_note = parts[1].strip()
                        nickname = history_note.split(' ')[0] if history_note else contact_name.split(' ')[0]
                        history_entries.append({
                            "contact_name": contact_name,
                            "nickname": nickname,
                            "history_note": history_note
                        })
                    except Exception as e:
                        logger.error(f"Failed to parse history entry '{history_text}': {e}")

            # Process history entries and create events
            synced_history_events = []
            try:
                for history in history_entries:
                    contact_name = history["contact_name"]
                    nickname = history["nickname"]
                    history_note = history["history_note"]

                    # Search for the contact in RealNex
                    query_params = {"$filter": f"fullName eq '{contact_name}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "contact", query_params, cursor))
                    contact_id = None
                    if search_results and len(search_results) > 0:
                        contact_id = search_results[0]["key"]
                    else:
                        # Create the contact if not found
                        try:
                            first_name = contact_name.split(' ')[0] if contact_name else ''
                            last_name = ' '.join(contact_name.split(' ')[1:]) if len(contact_name.split(' ')) > 1 else ''
                            with httpx.Client() as client:
                                response = client.post(
                                    "https://sync.realnex.com/api/v1/Crm/contact",
                                    headers={'Authorization': f'Bearer {realnex_token}'},
                                    json={
                                        "firstName": first_name,
                                        "lastName": last_name,
                                        "email": "",
                                        "mobile": "",
                                        "address": {"country": "USA"},
                                        "prospect": True,
                                        "investor": False,
                                        "doNotEmail": False,
                                        "doNotCall": False,
                                        "doNotFax": False,
                                        "doNotMail": False,
                                        "objectGroups": [{"key": realnex_group_id}],
                                        "source": "CRE Chat Bot"
                                    }
                                )
                                response.raise_for_status()
                                contact_response = response.json()
                                contact_id = contact_response.get("key")
                                synced_contacts.append({
                                    "id": contact_id,
                                    "firstName": first_name,
                                    "lastName": last_name,
                                    "email": "",
                                    "mobile": ""
                                })
                                cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                               (contact_id, contact_name, "", "", user_id))
                                conn.commit()
                                utils.log_change(user_id, "contact", contact_id, "created", {"firstName": first_name, "lastName": last_name, "changed_by": user_name}, cursor, conn)
                                # Sync history to RealNex
                                asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                        except Exception as e:
                            logger.error(f"Failed to create contact for history entry {contact_name}: {e}")
                            continue

                    # If the history note mentions "jokes," create an event
                    if "jokes" in history_note.lower():
                        event_subject = f"Call {nickname}, ask him a joke"
                        # Determine priority and alarm based on context
                        priority_key = 2 if "urgent" in history_note.lower() else 1  # Higher priority if urgent
                        alarm_minutes = 15 if "urgent" in history_note.lower() else 0  # Reminder 15 minutes before if urgent
                        event_data = {
                            "id": f"event_{len(synced_events) + len(synced_history_events)}_{user_id}",
                            "subject": event_subject,
                            "startDate": datetime.now().isoformat(),
                            "endDate": (datetime.now() + timedelta(minutes=30)).isoformat(),
                            "contact_id": contact_id,
                            "description": f"Note: {history_note}"
                        }
                        event_hash = utils.hash_entity(event_data, "event")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, event_hash))
                        if not cursor.fetchone():
                            # Search RealNex to avoid duplicates
                            query_params = {"$filter": f"subject eq '{event_data['subject']}' and startDate eq '{event_data['startDate']}'"}
                            search_results = asyncio.run(utils.search_realnex_entities(user_id, "event", query_params, cursor))
                            if search_results and len(search_results) > 0:
                                utils.log_duplicate(user_id, event_data, "event", cursor, conn)
                                continue

                            try:
                                with httpx.Client() as client:
                                    response = client.post(
                                        "https://sync.realnex.com/api/v1/Crm/event",
                                        headers={'Authorization': f'Bearer {realnex_token}'},
                                        json={
                                            "userKey": user_id,
                                            "subject": event_data["subject"],
                                            "description": event_data["description"],
                                            "startDate": event_data["startDate"],
                                            "endDate": event_data["endDate"],
                                            "timeZone": "UTC",
                                            "timeless": False,
                                            "allDay": False,
                                            "finished": False,
                                            "alarmMinutes": alarm_minutes,
                                            "eventType": {"key": 1},
                                            "priority": {"key": priority_key},
                                            "eventObjects": [{"type": "contact", "key": contact_id}],
                                            "objectGroups": [{"key": realnex_group_id}],
                                            "source": "CRE Chat Bot"
                                        }
                                    )
                                    response.raise_for_status()
                                    event_response = response.json()
                                    event_key = event_response.get("key", event_data["id"])
                                    event_data["id"] = event_key
                                    synced_history_events.append(event_data)
                                    utils.log_user_activity(user_id, "sync_realnex_event", {"event_id": event_data["id"], "group_id": realnex_group_id}, cursor, conn)
                                    utils.log_change(user_id, "event", event_data["id"], "created", {"subject": event_data["subject"], "changed_by": user_name}, cursor, conn)
                                    # Sync history to RealNex
                                    asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                            except Exception as e:
                                logger.error(f"Failed to create event for history entry {history_note}: {e}")
                                continue
                        else:
                            utils.log_duplicate(user_id, event_data, "event", cursor, conn)
                    else:
                        # Log the history note to RealNex history
                        try:
                            with httpx.Client() as client:
                                history_entry = {
                                    "entityType": "contact",
                                    "entityId": contact_id,
                                    "action": "note_added",
                                    "description": f"History note added for {contact_name}",
                                    "details": {"note": history_note},
                                    "changeDate": datetime.now().isoformat(),
                                    "user": {"userName": user_name}
                                }
                                response = client.post(
                                    "https://sync.realnex.com/api/v1/Crm/history",
                                    headers={'Authorization': f'Bearer {realnex_token}'},
                                    json=history_entry
                                )
                                response.raise_for_status()
                                utils.log_user_activity(user_id, "sync_realnex_history", {"contact_id": contact_id, "note": history_note}, cursor, conn)
                                utils.log_change(user_id, "contact", contact_id, "history_added", {"note": history_note, "changed_by": user_name}, cursor, conn)
                                # Sync history to RealNex
                                asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                        except Exception as e:
                            logger.error(f"Failed to log history note for {contact_name}: {e}")
                            continue
            except Exception as e:
                logger.error(f"Failed to process history entries in PDF: {e}")
                return jsonify({"error": f"Failed to process history entries: {str(e)}"}), 500

            logger.info(f"PDF file processed for user {user_id}—synced to RealNex like a boss! 🏢")
            return jsonify({
                "status": "PDF processed and synced to RealNex—another win for the CRE team! 🏆",
                "companies": synced_companies,
                "properties": synced_properties,
                "spaces": synced_spaces,
                "projects": synced_projects,
                "leasecomps": synced_leasecomps,
                "salecomps": synced_salecomps,
                "events": synced_events + synced_history_events
            })

        elif filename.endswith(('.png', '.jpg', '.jpeg')):
            # Process Image
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            contacts = []
            for line in text.split('\n'):
                if '@' in line:
                    email = line.strip()
                    name = text.split('\n')[0] if text.split('\n') else "Unknown"
                    contacts.append({
                        "Full Name": name,
                        "Email": email,
                        "Phone": "",
                        "Prospect": True,
                        "Investor": False
                    })

            # Process contacts
            realnex_token = utils.get_token(user_id, "realnex", cursor)
            realnex_group_id = utils.get_user_settings(user_id, cursor, conn).get("realnex_group_id")
            if not realnex_token or not realnex_group_id:
                return jsonify({"error": "RealNex token or group ID missing—can’t sync without the keys to the building! 🔑"}), 401

            synced_contacts = []
            for contact in contacts:
                contact_hash = utils.hash_entity(contact, "contact")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                               (user_id, contact_hash))
                if cursor.fetchone():
                    utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                    continue

                # Search RealNex to avoid duplicates
                email = contact.get('Email', '')
                full_name = contact.get('Full Name', '')
                if email or full_name:
                    query_params = {"$filter": f"email eq '{email}'" if email else f"fullName eq '{full_name}'"}
                    search_results = asyncio.run(utils.search_realnex_entities(user_id, "contact", query_params, cursor))
                    if search_results and len(search_results) > 0:
                        utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                        continue

                # Split Full Name into First and Last Name
                full_name = contact.get('Full Name', '')
                first_name = full_name.split(' ')[0] if full_name else ''
                last_name = ' '.join(full_name.split(' ')[1:]) if len(full_name.split(' ')) > 1 else ''

                contact_data = {
                    "id": f"contact_{len(synced_contacts)}_{user_id}",
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": contact.get('Email', ''),
                    "mobile": contact.get('Phone', ''),
                    "address": {"country": "USA"},
                    "prospect": contact.get('Prospect', True),
                    "investor": contact.get('Investor', False)
                }
                try:
                    with httpx.Client() as client:
                        response = client.post(
                            "https://sync.realnex.com/api/v1/Crm/contact",
                            headers={'Authorization': f'Bearer {realnex_token}'},
                            json={
                                "firstName": contact_data["firstName"],
                                "lastName": contact_data["lastName"],
                                "email": contact_data["email"],
                                "mobile": contact_data["mobile"],
                                "address": contact_data["address"],
                                "prospect": contact_data["prospect"],
                                "investor": contact_data["investor"],
                                "doNotEmail": False,
                                "doNotCall": False,
                                "doNotFax": False,
                                "doNotMail": False,
                                "objectGroups": [{"key": realnex_group_id}],
                                "source": "CRE Chat Bot"
                            }
                        )
                        response.raise_for_status()
                        contact_response = response.json()
                        contact_key = contact_response.get("key", contact_data["id"])
                        contact_data["id"] = contact_key
                        email_score = cmd_sync_data.check_email_health(contact_data["email"]) if contact_data["email"] else 0
                        phone_score = cmd_sync_data.check_phone_health(contact_data["mobile"]) if contact_data["mobile"] else 0
                        utils.log_health_history(user_id, contact_data["id"], email_score, phone_score, cursor, conn)
                        cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                       (contact_data["id"], full_name, contact_data["email"], contact_data["mobile"], user_id))
                        conn.commit()
                        utils.log_change(user_id, "contact", contact_data["id"], "created", {"firstName": contact_data["firstName"], "lastName": contact_data["lastName"], "changed_by": user_name}, cursor, conn)
                        synced_contacts.append(contact_data)
                        # Sync history to RealNex
                        asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
                except Exception as e:
                    logger.error(f"Failed to create contact {contact_data['id']} in RealNex: {e}")
                    return jsonify({"error": f"Failed to create contact: {str(e)}"}), 500

            logger.info(f"Image file processed for user {user_id}—synced to RealNex like a snapshot deal! 📸")
            return jsonify({
                "status": "Image processed and synced to RealNex—picture perfect! 🖼️",
                "contacts": synced_contacts
            })

        else:
            return jsonify({"error": "Unsupported file type—let’s stick to the CRE classics! 📜"}), 400

    except Exception as e:
        logger.error(f"Error processing file {filename} for user {user_id}: {e}")
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500
    finally:
        # Clean up: delete the file after processing
        try:
            os.remove(file_path)
            logger.info(f"Deleted temporary file: {file_path}—cleaned up like a pro property manager! 🧹")
        except Exception as e:
            logger.error(f"Failed to delete temporary file {file_path}: {e}")

@app.route('/settings', methods=['GET'])
@token_required
def settings_page(user_id):
    logger.info("Settings page accessed—tweaking the gears like a CRE master! ⚙️")
    settings = utils.get_user_settings(user_id, cursor, conn)
    return render_template('settings.html', settings=settings)

@app.route('/update-settings', methods=['POST'])
@token_required
def update_settings(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided—don’t leave me empty like an unleased office! 🏢"}), 400

    try:
        cursor.execute('''INSERT OR REPLACE INTO user_settings (user_id, language, subject_generator_enabled, 
                          deal_alerts_enabled, email_notifications, sms_notifications, mailchimp_group_id, 
                          constant_contact_group_id, realnex_group_id, apollo_group_id, seamless_group_id, zoominfo_group_id)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (user_id, data.get('language', 'en'), int(data.get('subject_generator_enabled', 0)),
                        int(data.get('deal_alerts_enabled', 0)), int(data.get('email_notifications', 0)),
                        int(data.get('sms_notifications', 0)), data.get('mailchimp_group_id', ''),
                        data.get('constant_contact_group_id', ''), data.get('realnex_group_id', ''),
                        data.get('apollo_group_id', ''), data.get('seamless_group_id', ''), data.get('zoominfo_group_id', '')))
        conn.commit()
        logger.info(f"Settings updated for user {user_id}—tuned up like a CRE deal ready to close! 🔧")
        return jsonify({"status": "Settings updated—looking sharp! ✨"})
    except Exception as e:
        logger.error(f"Failed to update settings for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update settings: {str(e)}"}), 500

@app.route('/set-token', methods=['POST'])
@token_required
def set_token(user_id):
    data = request.get_json()
    service = data.get('service')
    token = data.get('token')
    if not service or not token:
        return jsonify({"error": "Service and token are required—don’t make me chase you like a late rent payment! 💸"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                       (user_id, service, token))
        conn.commit()
        logger.info(f"Token set for service {service} for user {user_id}—locked in like a CRE contract! 🔒")
        return jsonify({"status": f"Token for {service} set successfully—ready to roll! 🚀"})
    except Exception as e:
        logger.error(f"Failed to set token for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set token: {str(e)}"}), 500

@app.route('/points', methods=['GET'])
@token_required
def get_points(user_id):
    try:
        cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            points_data = {"points": result[0], "email_credits": result[1], "has_msa": bool(result[2])}
        else:
            points_data = {"points": 0, "email_credits": 0, "has_msa": False}
            cursor.execute("INSERT INTO user_points (user_id, points, email_credits, has_msa) VALUES (?, ?, ?, ?)",
                           (user_id, 0, 0, 0))
            conn.commit()
        logger.info(f"Points retrieved for user {user_id}—their score is looking hot! 🔥")
        return jsonify(points_data)
    except Exception as e:
        logger.error(f"Failed to retrieve points for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve points: {str(e)}"}), 500

@app.route('/update-points', methods=['POST'])
@token_required
def update_points(user_id):
    data = request.get_json()
    points = data.get('points', 0)
    email_credits = data.get('email_credits', 0)
    has_msa = data.get('has_msa', False)

    try:
        cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, email_credits, has_msa) VALUES (?, ?, ?, ?)",
                       (user_id, points, email_credits, int(has_msa)))
        conn.commit()
        logger.info(f"Points updated for user {user_id}: points={points}, email_credits={email_credits}, has_msa={has_msa}—they’re climbing the CRE leaderboard! 📊")
        return jsonify({"status": "Points updated—your CRE game is strong! 💪"})
    except Exception as e:
        logger.error(f"Failed to update points for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update points: {str(e)}"}), 500

@app.route('/onboarding-status', methods=['GET'])
@token_required
def get_onboarding_status(user_id):
    try:
        cursor.execute("SELECT step, completed FROM user_onboarding WHERE user_id = ?", (user_id,))
        steps = cursor.fetchall()
        onboarding_status = {step: bool(completed) for step, completed in steps}
        logger.info(f"Onboarding status retrieved for user {user_id}—they’re navigating CRE like a pro! 🧭")
        return jsonify(onboarding_status)
    except Exception as e:
        logger.error(f"Failed to retrieve onboarding status for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve onboarding status: {str(e)}"}), 500

@app.route('/update-onboarding', methods=['POST'])
@token_required
def update_onboarding(user_id):
    data = request.get_json()
    step = data.get('step')
    completed = data.get('completed', False)
    if not step:
        return jsonify({"error": "Step is required—don’t skip steps like a rushed lease signing! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, ?)",
                       (user_id, step, int(completed)))
        conn.commit()
        logger.info(f"Onboarding step {step} updated for user {user_id}: completed={completed}—they’re one step closer to CRE mastery! 🏆")
        return jsonify({"status": f"Onboarding step {step} updated—nice progress! 🚀"})
    except Exception as e:
        logger.error(f"Failed to update onboarding for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update onboarding: {str(e)}"}), 500

@app.route('/deal-alerts', methods=['GET'])
@token_required
def get_deal_alerts(user_id):
    try:
        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            alert_data = {"threshold": result[0], "deal_type": result[1]}
        else:
            alert_data = {"threshold": 0, "deal_type": "none"}
        logger.info(f"Deal alerts retrieved for user {user_id}—keeping an eye on the CRE market! 👀")
        return jsonify(alert_data)
    except Exception as e:
        logger.error(f"Failed to retrieve deal alerts for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve deal alerts: {str(e)}"}), 500

@app.route('/set-deal-alert', methods=['POST'])
@token_required
def set_deal_alert(user_id):
    data = request.get_json()
    threshold = data.get('threshold')
    deal_type = data.get('deal_type')
    if threshold is None or not deal_type:
        return jsonify({"error": "Threshold and deal type are required—don’t leave me hanging like an unsigned lease! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold, deal_type) VALUES (?, ?, ?)",
                       (user_id, float(threshold), deal_type))
        conn.commit()
        logger.info(f"Deal alert set for user {user_id}: threshold={threshold}, deal_type={deal_type}—they’re ready to catch big CRE deals! 🎣")
        return jsonify({"status": "Deal alert set—time to snag those deals! 🏢"})
    except Exception as e:
        logger.error(f"Failed to set deal alert for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set deal alert: {str(e)}"}), 500

@app.route('/generate-2fa', methods=['POST'])
@token_required
def generate_2fa(user_id):
    import random
    try:
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        expiry = datetime.now() + timedelta(minutes=10)
        cursor.execute("INSERT OR REPLACE INTO two_fa_codes (user_id, code, expiry) VALUES (?, ?, ?)",
                       (user_id, code, expiry.isoformat()))
        conn.commit()
        logger.info(f"2FA code generated for user {user_id}: code={code}, expires={expiry}—they’re locked in tighter than a CRE vault! 🔒")
        return jsonify({"status": "2FA code generated", "code": code, "expiry": expiry.isoformat()})
    except Exception as e:
        logger.error(f"Failed to generate 2FA code for user {user_id}: {e}")
        return jsonify({"error": f"Failed to generate 2FA code: {str(e)}"}), 500

@app.route('/verify-2fa', methods=['POST'])
@token_required
def verify_2fa(user_id):
    data = request.get_json()
    code = data.get('code')
    if not code:
        return jsonify({"error": "Code is required—don’t leave me hanging like a bad lease deal! 🏢"}), 400

    try:
        cursor.execute("SELECT code, expiry FROM two_fa_codes WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "No 2FA code found—did you forget to generate one? 🔑"}), 404

        stored_code, expiry = result
        expiry_time = datetime.fromisoformat(expiry)
        if datetime.now() > expiry_time:
            return jsonify({"error": "2FA code expired—faster than a hot property listing! ⏰"}), 400

        if code != stored_code:
            return jsonify({"error": "Invalid code—try again, champ! 🔐"}), 400

        # Code is valid, clean up
        cursor.execute("DELETE FROM two_fa_codes WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"2FA code verified for user {user_id}—they’re in like a VIP tenant! 🏙️")
        return jsonify({"status": "2FA verified—welcome to the penthouse! 🏙️"})
    except Exception as e:
        logger.error(f"Failed to verify 2FA for user {user_id}: {e}")
        return jsonify({"error": f"Failed to verify 2FA: {str(e)}"}), 500

@app.route('/chat', methods=['POST'])
@token_required
def chat(user_id):
    data = request.get_json()
    message = data.get('message')
    if not message:
        return jsonify({"error": "Message is required—don’t ghost me like an empty office space! 👻"}), 400

    try:
        # Save user message
        timestamp = datetime.now().isoformat()
        cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                       (user_id, "user", message, timestamp))
        conn.commit()

        # Process the message with AI (simplified for this example)
        bot_response = commands.process_message(message, user_id, cursor, conn, socketio)
        if not bot_response:
            bot_response = f"Echo from the CRE world: {message}—let’s lease this conversation! 🏢"

        cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                       (user_id, "bot", bot_response, datetime.now().isoformat()))
        conn.commit()

        # Emit to SocketIO for real-time chat
        socketio.emit('message', {
            "user_id": user_id,
            "sender": "bot",
            "message": bot_response,
            "timestamp": timestamp
        }, namespace='/chat')

        # Check for webhook and notify
        cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
        webhook = cursor.fetchone()
        if webhook:
            webhook_url = webhook[0]
            try:
                with httpx.Client() as client:
                    client.post(webhook_url, json={
                        "user_id": user_id,
                        "message": message,
                        "response": bot_response,
                        "timestamp": timestamp
                    })
            except Exception as e:
                logger.error(f"Failed to send webhook notification for user {user_id}: {e}")

        logger.info(f"Chat message processed for user {user_id}: {message}—they’re chatting like a CRE pro! 💬")
        return jsonify({"status": "Message processed", "response": bot_response})
    except Exception as e:
        logger.error(f"Failed to process chat message for user {user_id}: {e}")
        return jsonify({"error": f"Failed to process message: {str(e)}"}), 500

@app.route('/chat-history', methods=['GET'])
@token_required
def get_chat_history(user_id):
    try:
        cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp ASC",
                       (user_id,))
        messages = [{"sender": row[0], "message": row[1], "timestamp": row[2]} for row in cursor.fetchall()]
        logger.info(f"Chat history retrieved for user {user_id}—their conversation is hotter than a CRE market boom! 🔥")
        return jsonify({"messages": messages})
    except Exception as e:
        logger.error(f"Failed to retrieve chat history for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve chat history: {str(e)}"}), 500

@app.route('/deals', methods=['GET'])
@token_required
def get_deals(user_id):
    try:
        cursor.execute("SELECT id, amount, close_date FROM deals WHERE user_id = ?", (user_id,))
        deals = [{"id": row[0], "amount": row[1], "close_date": row[2]} for row in cursor.fetchall()]
        logger.info(f"Deals retrieved for user {user_id}—their portfolio is looking sweet! 🏢")
        return jsonify({"deals": deals})
    except Exception as e:
        logger.error(f"Failed to retrieve deals for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve deals: {str(e)}"}), 500

@app.route('/add-deal', methods=['POST'])
@token_required
def add_deal(user_id):
    data = request.get_json()
    deal_id = data.get('id')
    amount = data.get('amount')
    close_date = data.get('close_date')
    if not all([deal_id, amount, close_date]):
        return jsonify({"error": "Deal ID, amount, and close date are required—don’t leave me hanging like an unsigned lease! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                       (deal_id, amount, close_date, user_id))
        conn.commit()

        # Check deal alerts
        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        alert = cursor.fetchone()
        if alert and float(amount) >= float(alert[0]):
            socketio.emit('deal_alert', {
                'user_id': user_id,
                'message': f"Deal alert: New {alert[1]} deal of ${amount} (threshold: {alert[0]})",
                'deal_type': alert[1]
            }, namespace='/chat')

        logger.info(f"Deal added for user {user_id}: id={deal_id}, amount={amount}—time to pop the champagne! 🍾")
        return jsonify({"status": "Deal added—another win for the CRE team! 🏆"})
    except Exception as e:
        logger.error(f"Failed to add deal for user {user_id}: {e}")
        return jsonify({"error": f"Failed to add deal: {str(e)}"}), 500

@app.route('/contacts', methods=['GET'])
@token_required
def get_contacts(user_id):
    try:
        cursor.execute("SELECT id, name, email, phone FROM contacts WHERE user_id = ?", (user_id,))
        contacts = [{"id": row[0], "name": row[1], "email": row[2], "phone": row[3]} for row in cursor.fetchall()]
        logger.info(f"Contacts retrieved for user {user_id}—their network is bigger than a CRE convention! 🤝")
        return jsonify({"contacts": contacts})
    except Exception as e:
        logger.error(f"Failed to retrieve contacts for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve contacts: {str(e)}"}), 500

@app.route('/add-contact', methods=['POST'])
@token_required
def add_contact(user_id):
    data = request.get_json()
    contact_id = data.get('id')
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone')
    if not all([contact_id, name, email, phone]):
        return jsonify({"error": "Contact ID, name, email, and phone are required—don’t leave me empty-handed! 📞"}), 400

    try:
        contact_data = {"id": contact_id, "name": name, "email": email, "phone": phone}
        contact_hash = utils.hash_entity(contact_data, "contact")
        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                       (user_id, contact_hash))
        if cursor.fetchone():
            utils.log_duplicate(user_id, contact_data, "contact", cursor, conn)
            logger.info(f"Duplicate contact detected for user {user_id}: {contact_id}—logged it like a pro! 🧹")
            return jsonify({"status": "Duplicate contact detected and logged"})

        cursor.execute("INSERT OR REPLACE INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                       (contact_id, name, email, phone, user_id))
        conn.commit()

        # Sync to RealNex
        realnex_token = utils.get_token(user_id, "realnex", cursor)
        realnex_group_id = utils.get_user_settings(user_id, cursor, conn).get("realnex_group_id")
        if realnex_token and realnex_group_id:
            first_name = name.split(' ')[0] if name else ''
            last_name = ' '.join(name.split(' ')[1:]) if len(name.split(' ')) > 1 else ''
            try:
                with httpx.Client() as client:
                    response = client.post(
                        "https://sync.realnex.com/api/v1/Crm/contact",
                        headers={'Authorization': f'Bearer {realnex_token}'},
                        json={
                            "firstName": first_name,
                            "lastName": last_name,
                            "email": email,
                            "mobile": phone,
                            "address": {"country": "USA"},
                            "prospect": True,
                            "investor": False,
                            "doNotEmail": False,
                            "doNotCall": False,
                            "doNotFax": False,
                            "doNotMail": False,
                            "objectGroups": [{"key": realnex_group_id}],
                            "source": "CRE Chat Bot"
                        }
                    )
                    response.raise_for_status()
                    contact_response = response.json()
                    contact_key = contact_response.get("key", contact_id)
                    email_score = cmd_sync_data.check_email_health(email) if email else 0
                    phone_score = cmd_sync_data.check_phone_health(phone) if phone else 0
                    utils.log_health_history(user_id, contact_key, email_score, phone_score, cursor, conn)
                    utils.log_user_activity(user_id, "sync_realnex_contact", {"contact_id": contact_key, "group_id": realnex_group_id}, cursor, conn)
                    # Sync history to RealNex
                    import asyncio
                    asyncio.run(utils.sync_changes_to_realnex(user_id, cursor, conn))
            except Exception as e:
                logger.error(f"Failed to sync contact {contact_id} to RealNex for user {user_id}: {e}")

        logger.info(f"Contact added for user {user_id}: id={contact_id}—their CRE network just grew! 🌐")
        return jsonify({"status": "Contact added—ready to make some deals! 🤝"})
    except Exception as e:
        logger.error(f"Failed to add contact for user {user_id}: {e}")
        return jsonify({"error": f"Failed to add contact: {str(e)}"}), 500

@app.route('/set-webhook', methods=['POST'])
@token_required
def set_webhook(user_id):
    data = request.get_json()
    webhook_url = data.get('webhook_url')
    if not webhook_url:
        return jsonify({"error": "Webhook URL is required—don’t make me chase you like a late rent payment! 💸"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                       (user_id, webhook_url))
        conn.commit()
        logger.info(f"Webhook set for user {user_id}: {webhook_url}—ready to roll like a CRE deal on fire! 🔥")
        return jsonify({"status": "Webhook set—let’s keep the CRE notifications flowing! 📬"})
    except Exception as e:
        logger.error(f"Failed to set webhook for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set webhook: {str(e)}"}), 500

@app.route('/health-history', methods=['GET'])
@token_required
def get_health_history(user_id):
    try:
        cursor.execute("SELECT contact_id, email_health_score, phone_health_score, timestamp FROM health_history WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        history = [{"contact_id": row[0], "email_health_score": row[1], "phone_health_score": row[2], "timestamp": row[3]}
                   for row in cursor.fetchall()]
        logger.info(f"Health history retrieved for user {user_id}—their contacts are in top shape! 🩺")
        return jsonify({"health_history": history})
    except Exception as e:
        logger.error(f"Failed to retrieve health history for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve health history: {str(e)}"}), 500

@app.route('/generate-report', methods=['POST'])
@token_required
def generate_report(user_id):
    data = request.get_json()
    report_type = data.get('report_type')
    if not report_type:
        return jsonify({"error": "Report type is required—don’t leave me guessing like a CRE appraisal! 📊"}), 400

    try:
        if report_type == "duplicates":
            cursor.execute("SELECT contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ?",
                           (user_id,))
            duplicates = [{"contact_hash": row[0], "contact_data": json.loads(row[1]), "timestamp": row[2]}
                          for row in cursor.fetchall()]
            pdf = generate_pdf_report(user_id, {"Duplicates Found": len(duplicates)}, "Duplicates Report")
            logger.info(f"Duplicates report generated for user {user_id}—cleaning up like a pro! 🧹")
            return send_file(pdf, as_attachment=True, download_name="duplicates_report.pdf", mimetype='application/pdf')

        elif report_type == "activity":
            cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ?",
                           (user_id,))
            activities = [{"action": row[0], "details": json.loads(row[1]), "timestamp": row[2]}
                          for row in cursor.fetchall()]
            pdf = generate_pdf_report(user_id, {"Total Activities": len(activities)}, "Activity Report")
            logger.info(f"Activity report generated for user {user_id}—their moves are documented! 📝")
            return send_file(pdf, as_attachment=True, download_name="activity_report.pdf", mimetype='application/pdf')

        else:
            return jsonify({"error": "Unsupported report type—let’s stick to the CRE classics! 📜"}), 400
    except Exception as e:
        logger.error(f"Failed to generate report for user {user_id}: {e}")
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500

@app.route('/duplicates-log', methods=['GET'])
@token_required
def get_duplicates_log(user_id):
    try:
        cursor.execute("SELECT id, contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        duplicates = [{"id": row[0], "contact_hash": row[1], "contact_data": json.loads(row[2]), "timestamp": row[3]}
                      for row in cursor.fetchall()]
        logger.info(f"Duplicates log retrieved for user {user_id}—cleaning up faster than a property manager! 🧹")
        return jsonify({"duplicates": duplicates})
    except Exception as e:
        logger.error(f"Failed to retrieve duplicates log for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve duplicates log: {str(e)}"}), 500

@app.route('/group-by-history-date', methods=['POST'])
@token_required
def group_by_history_date(user_id):
    data = request.get_json()
    days_ago = data.get('days_ago')
    group_name = data.get('group_name', f"History_{days_ago}_Days_Ago")
    
    if days_ago is None:
        return jsonify({"error": "days_ago is required—don’t leave me in the past! ⏳"}), 400

    try:
        days_ago = int(days_ago)
        if days_ago < 0:
            return jsonify({"error": "days_ago must be a non-negative integer—time travel isn’t a CRE thing yet! 🕰️"}), 400
    except ValueError:
        return jsonify({"error": "days_ago must be an integer—let’s keep the numbers straight! 🔢"}), 400

    cutoff_date = (datetime.now() - timedelta(days=days_ago)).isoformat()
    
    # Fetch history entries from RealNex
    realnex_token = utils.get_token(user_id, "realnex", cursor)
    realnex_group_id = utils.get_user_settings(user_id, cursor, conn).get("realnex_group_id")
    if not realnex_token or not realnex_group_id:
        return jsonify({"error": "RealNex token or group ID missing—can’t sync without the keys to the building! 🔑"}), 401

    try:
        with httpx.Client() as client:
            # Fetch history entries since cutoff date
            query_params = {"$filter": f"changeDate ge '{cutoff_date}'"}
            response = client.get(
                "https://sync.realnex.com/api/v1/Crm/history",
                headers={'Authorization': f'Bearer {realnex_token}'},
                params=query_params
            )
            response.raise_for_status()
            history_entries = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch history from RealNex for user {user_id}: {e}")
        return jsonify({"error": f"Failed to fetch history: {str(e)}"}), 500

    # Group contacts by history entries
    grouped_contacts = []
    processed_contact_ids = set()

    for entry in history_entries:
        if entry.get("entityType") != "contact":
            continue
        contact_id = entry.get("entityId")
        if contact_id in processed_contact_ids:
            continue

        try:
            # Fetch contact details
            with httpx.Client() as client:
                response = client.get(
                    f"https://sync.realnex.com/api/v1/Crm/contact/{contact_id}",
                    headers={'Authorization': f'Bearer {realnex_token}'}
                )
                response.raise_for_status()
                contact = response.json()
                grouped_contacts.append({
                    "contact_id": contact_id,
                    "fullName": contact.get("fullName", ""),
                    "email": contact.get("email", ""),
                    "history_note": entry.get("details", {}).get("note", "")
                })
                processed_contact_ids.add(contact_id)
        except Exception as e:
            logger.error(f"Failed to fetch contact {contact_id} from RealNex for user {user_id}: {e}")
            continue

    # Assign contacts to a new group in RealNex
    try:
        with httpx.Client() as client:
            # Create a new group
            response = client.post(
                "https://sync.realnex.com/api/v1/Crm/objectgroup",
                headers={'Authorization': f'Bearer {realnex_token}'},
                json={
                    "name": group_name,
                    "type": "contact",
                    "source": "CRE Chat Bot"
                }
            )
            response.raise_for_status()
            new_group = response.json()
            new_group_id = new_group.get("key")

            # Assign contacts to the group
            for contact in grouped_contacts:
                contact_id = contact["contact_id"]
                response = client.put(
                    f"https://sync.realnex.com/api/v1/Crm/contact/{contact_id}",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    json={
                        "objectGroups": [{"key": new_group_id}]
                    }
                )
                response.raise_for_status()
                utils.log_user_activity(user_id, "group_by_history", 
                                      {"contact_id": contact_id, "group_id": new_group_id}, 
                                      cursor, conn)
    except Exception as e:
        logger.error(f"Failed to create group or assign contacts in RealNex for user {user_id}: {e}")
        return jsonify({"error": f"Failed to group contacts: {str(e)}"}), 500

    logger.info(f"Contacts grouped under {group_name} for user {user_id}—organized like a CRE pro! 📋")
    return jsonify({
        "status": f"Contacts grouped under {group_name}—nice work, team! 🤝",
        "group_id": new_group_id,
        "contacts": grouped_contacts
    })

@app.route('/trigger-for-contact', methods=['POST'])
@token_required
def trigger_for_contact(user_id):
    data = request.get_json()
    contact_id = data.get('contact_id')
    trigger_type = data.get('trigger_type')  # e.g., "email", "sms", "call"
    schedule_time = data.get('schedule_time')  # ISO format
    message = data.get('message', '')

    if not all([contact_id, trigger_type, schedule_time]):
        return jsonify({"error": "Contact ID, trigger type, and schedule time are required—don’t leave me hanging! 🕒"}), 400

    # Validate trigger type
    valid_triggers = ["email", "sms", "call"]
    if trigger_type not in valid_triggers:
        return jsonify({"error": f"Invalid trigger type. Must be one of {valid_triggers}—let’s keep it CRE-friendly! 📧"}), 400

    # Fetch contact details from RealNex
    realnex_token = utils.get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return jsonify({"error": "RealNex token missing—can’t sync without the keys to the building! 🔑"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                f"https://sync.realnex.com/api/v1/Crm/contact/{contact_id}",
                headers={'Authorization': f'Bearer {realnex_token}'}
            )
            response.raise_for_status()
            contact = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch contact {contact_id} from RealNex for user {user_id}: {e}")
        return jsonify({"error": f"Failed to fetch contact: {str(e)}"}), 500

    # Prepare task data
    task_data = {
        "contact_id": contact_id,
        "fullName": contact.get("fullName", ""),
        "email": contact.get("email", ""),
        "phone": contact.get("mobile", ""),
        "trigger_type": trigger_type,
        "message": message
    }

    # Schedule the task
    try:
        cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, f"trigger_{trigger_type}", json.dumps(task_data), schedule_time, "pending"))
        conn.commit()

        # Log the activity
        utils.log_user_activity(user_id, "schedule_trigger", 
                              {"contact_id": contact_id, "trigger_type": trigger_type, "schedule_time": schedule_time}, 
                              cursor, conn)

        # Emit WebSocket notification
        socketio.emit('task_scheduled', {
            'user_id': user_id,
            'message': f"Scheduled {trigger_type} trigger for {contact.get('fullName', 'contact')} at {schedule_time}"
        }, namespace='/chat')

        logger.info(f"Trigger scheduled for user {user_id}: {trigger_type} for contact {contact_id}—set to go off like a CRE alarm! ⏰")
        return jsonify({
            "status": f"{trigger_type.capitalize()} trigger scheduled for contact {contact_id}—ready to make waves! 🌊",
            "task_data": task_data,
            "schedule_time": schedule_time
        })
    except Exception as e:
        logger.error(f"Failed to schedule trigger for user {user_id}: {e}")
        return jsonify({"error": f"Failed to schedule trigger: {str(e)}"}), 500

@app.route('/activity-log', methods=['GET'])
@token_required
def get_activity_log(user_id):
    try:
        cursor.execute("SELECT id, action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        activities = [{"id": row[0], "action": row[1], "details": json.loads(row[2]), "timestamp": row[3]}
                      for row in cursor.fetchall()]
        logger.info(f"Activity log retrieved for user {user_id}—their moves are smoother than a CRE deal closing! 🏢")
        return jsonify({"activities": activities})
    except Exception as e:
        logger.error(f"Failed to retrieve activity log for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve activity log: {str(e)}"}), 500

@app.route('/email-template', methods=['POST'])
@token_required
def save_email_template(user_id):
    data = request.get_json()
    template_name = data.get('template_name')
    subject = data.get('subject')
    body = data.get('body')
    if not all([template_name, subject, body]):
        return jsonify({"error": "Template name, subject, and body are required—don’t leave my inbox empty! 📧"}), 400

    try:
        cursor.execute("INSERT INTO email_templates (user_id, template_name, subject, body) VALUES (?, ?, ?, ?)",
                       (user_id, template_name, subject, body))
        conn.commit()
        logger.info(f"Email template saved for user {user_id}: {template_name}—ready to send some CRE magic! ✨")
        return jsonify({"status": "Email template saved—your CRE emails are about to shine! 🌟"})
    except Exception as e:
        logger.error(f"Failed to save email template for user {user_id}: {e}")
        return jsonify({"error": f"Failed to save email template: {str(e)}"}), 500

@app.route('/email-templates', methods=['GET'])
@token_required
def get_email_templates(user_id):
    try:
        cursor.execute("SELECT id, template_name, subject, body FROM email_templates WHERE user_id = ?",
                       (user_id,))
        templates = [{"id": row[0], "template_name": row[1], "subject": row[2], "body": row[3]}
                     for row in cursor.fetchall()]
        logger.info(f"Email templates retrieved for user {user_id}—their inbox game is strong! 📬")
        return jsonify({"templates": templates})
    except Exception as e:
        logger.error(f"Failed to retrieve email templates for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve email templates: {str(e)}"}), 500

@app.route('/schedule-task', methods=['POST'])
@token_required
def schedule_task(user_id):
    data = request.get_json()
    task_type = data.get('task_type')
    task_data = data.get('task_data')
    schedule_time = data.get('schedule_time')
    if not all([task_type, task_data, schedule_time]):
        return jsonify({"error": "Task type, task data, and schedule time are required—don’t leave me waiting! ⏰"}), 400

    try:
        cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, task_type, json.dumps(task_data), schedule_time, "pending"))
        conn.commit()
        logger.info(f"Task scheduled for user {user_id}: type={task_type}, time={schedule_time}—set to go off like a CRE deadline! 📅")
        return jsonify({"status": "Task scheduled—let’s keep the CRE momentum going! 🚀"})
    except Exception as e:
        logger.error(f"Failed to schedule task for user {user_id}: {e}")
        return jsonify({"error": f"Failed to schedule task: {str(e)}"}), 500

@app.route('/scheduled-tasks', methods=['GET'])
@token_required
def get_scheduled_tasks(user_id):
    try:
        cursor.execute("SELECT id, task_type, task_data, schedule_time, status FROM scheduled_tasks WHERE user_id = ?",
                       (user_id,))
        tasks = [{"id": row[0], "task_type": row[1], "task_data": json.loads(row[2]), "schedule_time": row[3], "status": row[4]}
                 for row in cursor.fetchall()]
        logger.info(f"Scheduled tasks retrieved for user {user_id}—their calendar is busier than a CRE broker! 🗓️")
        return jsonify({"tasks": tasks})
    except Exception as e:
        logger.error(f"Failed to retrieve scheduled tasks for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve scheduled tasks: {str(e)}"}), 500

# WebSocket Events
@socketio.on('connect', namespace='/chat')
def handle_connect():
    logger.info("Client connected to /chat namespace—time to chat like a CRE pro! 💬")

@socketio.on('disconnect', namespace='/chat')
def handle_disconnect():
    logger.info("Client disconnected from /chat namespace—hope they signed the lease before leaving! 📝")

@socketio.on('join')
def handle_join(data):
    user_id = data.get('user_id')
    if user_id:
        join_room(user_id)
        logger.info(f"User {user_id} joined SocketIO room—ready to chat about CRE deals! 💬")

# Run the app
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))  # Use $PORT if available, else default to 5000
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
