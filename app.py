import os
import json
import logging
import redis
import jwt
import httpx
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
from flask_socketio import SocketIO
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
    logger.info("Redirecting to chat hub.")
    return redirect(url_for('chat_hub'))

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
    historical_data = [
        {"sq_ft": 1000, "rent_month": 2000, "sale_price": 500000, "deal_type": "LeaseComp"},
        {"sq_ft": 2000, "rent_month": 3500, "sale_price": 750000, "deal_type": "LeaseComp"},
        {"sq_ft": 3000, "rent_month": 5000, "sale_price": 1000000, "deal_type": "SaleComp"},
        {"sq_ft": 4000, "rent_month": 6500, "sale_price": 1200000, "deal_type": "SaleComp"}
    ]
    lease_data = [item for item in historical_data if item["deal_type"] == "LeaseComp"]
    sale_data = [item for item in historical_data if item["deal_type"] == "SaleComp"]
    return render_template('deal_trends.html', lease_data=lease_data, sale_data=sale_data)

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

@app.route('/upload-file', methods=['POST'])
@token_required
def upload_file(user_id):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Securely save the file
    filename = file.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Determine file type and process
    try:
        if filename.endswith('.xlsx'):
            # Process XLSX
            df = pd.read_excel(file_path)
            contacts = df.to_dict('records')
            for contact in contacts:
                contact_hash = utils.hash_entity(contact, "contact")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                               (user_id, contact_hash))
                if cursor.fetchone():
                    utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                else:
                    contact_id = f"contact_{len(contacts)}_{user_id}"
                    email_score = cmd_sync_data.check_email_health(contact.get('Email', '')) if contact.get('Email') else 0
                    phone_score = cmd_sync_data.check_phone_health(contact.get('Phone', '')) if contact.get('Phone') else 0
                    utils.log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                    cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                   (contact_id, contact.get('Full Name', ''), contact.get('Email', ''), contact.get('Phone', ''), user_id))
                    conn.commit()
            return jsonify({"status": "XLSX processed", "contacts": contacts})

        elif filename.endswith('.pdf'):
            # Process PDF
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            # Basic parsing for contacts (simplified)
            contacts = []
            for line in text.split('\n'):
                if '@' in line:
                    email = line.strip()
                    name = text.split('\n')[0] if text.split('\n') else "Unknown"
                    contacts.append({"Full Name": name, "Email": email, "Phone": ""})
            for contact in contacts:
                contact_hash = utils.hash_entity(contact, "contact")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                               (user_id, contact_hash))
                if cursor.fetchone():
                    utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                else:
                    contact_id = f"contact_{len(contacts)}_{user_id}"
                    email_score = cmd_sync_data.check_email_health(contact.get('Email', '')) if contact.get('Email') else 0
                    phone_score = cmd_sync_data.check_phone_health(contact.get('Phone', '')) if contact.get('Phone') else 0
                    utils.log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                    cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                   (contact_id, contact.get('Full Name', ''), contact.get('Email', ''), contact.get('Phone', ''), user_id))
                    conn.commit()
            return jsonify({"status": "PDF processed", "contacts": contacts})

        elif filename.endswith(('.png', '.jpg', '.jpeg')):
            # Process Image (Business Card or Camera Image)
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            # Basic parsing for contacts (simplified)
            contacts = []
            for line in text.split('\n'):
                if '@' in line:
                    email = line.strip()
                    name = text.split('\n')[0] if text.split('\n') else "Unknown"
                    contacts.append({"Full Name": name, "Email": email, "Phone": ""})
            for contact in contacts:
                contact_hash = utils.hash_entity(contact, "contact")
                cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?",
                               (user_id, contact_hash))
                if cursor.fetchone():
                    utils.log_duplicate(user_id, contact, "contact", cursor, conn)
                else:
                    contact_id = f"contact_{len(contacts)}_{user_id}"
                    email_score = cmd_sync_data.check_email_health(contact.get('Email', '')) if contact.get('Email') else 0
                    phone_score = cmd_sync_data.check_phone_health(contact.get('Phone', '')) if contact.get('Phone') else 0
                    utils.log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                    cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                   (contact_id, contact.get('Full Name', ''), contact.get('Email', ''), contact.get('Phone', ''), user_id))
                    conn.commit()
            return jsonify({"status": "Image processed", "contacts": contacts})

        else:
            return jsonify({"error": "Unsupported file type"}), 400

    finally:
        # Clean up the file
        if os.path.exists(file_path):
            os.remove(file_path)

@app.route('/settings', methods=['GET'])
@token_required
def settings_page(user_id):
    logger.info("Settings page accessed.")
    return render_template('settings.html')

@app.route('/authorize-mailchimp', methods=['GET'])
@token_required
def authorize_mailchimp(user_id):
    # Redirect to Mailchimp OAuth URL (simplified for demo; in production, use proper OAuth flow)
    mailchimp_client_id = os.getenv('MAILCHIMP_CLIENT_ID', 'your_client_id')
    redirect_uri = 'http://localhost:8000/mailchimp-callback'
    mailchimp_auth_url = f"https://login.mailchimp.com/oauth2/authorize?client_id={mailchimp_client_id}&redirect_uri={redirect_uri}&response_type=code"
    return redirect(mailchimp_auth_url)

@app.route('/mailchimp-callback', methods=['GET'])
@token_required
def mailchimp_callback(user_id):
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not found"}), 400

    # Exchange code for access token
    mailchimp_client_id = os.getenv('MAILCHIMP_CLIENT_ID', 'your_client_id')
    mailchimp_client_secret = os.getenv('MAILCHIMP_CLIENT_SECRET', 'your_client_secret')
    redirect_uri = 'http://localhost:8000/mailchimp-callback'

    try:
        with httpx.Client() as client:
            response = client.post(
                "https://login.mailchimp.com/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": mailchimp_client_id,
                    "client_secret": mailchimp_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code
                }
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get('access_token')

            # Save the token
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, "mailchimp", access_token))
            conn.commit()

            # Redirect back to settings
            return redirect('/settings')
    except Exception as e:
        logger.error(f"Mailchimp authorization failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/authorize-constant-contact', methods=['GET'])
@token_required
def authorize_constant_contact(user_id):
    # Redirect to Constant Contact OAuth URL (simplified for demo; in production, use proper OAuth flow)
    cc_client_id = os.getenv('CC_CLIENT_ID', 'your_client_id')
    redirect_uri = 'http://localhost:8000/constant-contact-callback'
    cc_auth_url = f"https://authz.constantcontact.com/oauth2/authorize?client_id={cc_client_id}&redirect_uri={redirect_uri}&response_type=code&scope=contact_data"
    return redirect(cc_auth_url)

@app.route('/constant-contact-callback', methods=['GET'])
@token_required
def constant_contact_callback(user_id):
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not found"}), 400

    # Exchange code for access token
    cc_client_id = os.getenv('CC_CLIENT_ID', 'your_client_id')
    cc_client_secret = os.getenv('CC_CLIENT_SECRET', 'your_client_secret')
    redirect_uri = 'http://localhost:8000/constant-contact-callback'

    try:
        with httpx.Client() as client:
            response = client.post(
                "https://authz.constantcontact.com/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": cc_client_id,
                    "client_secret": cc_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code
                }
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get('access_token')

            # Save the token
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, "constant_contact", access_token))
            conn.commit()

            # Redirect back to settings
            return redirect('/settings')
    except Exception as e:
        logger.error(f"Constant Contact authorization failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/authorize-apollo', methods=['GET'])
@token_required
def authorize_apollo(user_id):
    # Redirect to Apollo.io OAuth URL (simplified for demo; in production, use proper OAuth flow)
    apollo_client_id = os.getenv('APOLLO_CLIENT_ID', 'your_client_id')
    redirect_uri = 'http://localhost:8000/apollo-callback'
    apollo_auth_url = f"https://app.apollo.io/oauth/authorize?client_id={apollo_client_id}&redirect_uri={redirect_uri}&response_type=code"
    return redirect(apollo_auth_url)

@app.route('/apollo-callback', methods=['GET'])
@token_required
def apollo_callback(user_id):
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not found"}), 400

    # Exchange code for access token
    apollo_client_id = os.getenv('APOLLO_CLIENT_ID', 'your_client_id')
    apollo_client_secret = os.getenv('APOLLO_CLIENT_SECRET', 'your_client_secret')
    redirect_uri = 'http://localhost:8000/apollo-callback'

    try:
        with httpx.Client() as client:
            response = client.post(
                "https://app.apollo.io/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": apollo_client_id,
                    "client_secret": apollo_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code
                }
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get('access_token')

            # Save the token
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, "apollo", access_token))
            conn.commit()

            # Register webhook for Apollo.io
            webhook_url = f"http://your-app-url/webhook/apollo?user_id={user_id}"
            response = client.post(
                "https://api.apollo.io/v1/webhooks",
                headers={'Authorization': f'Bearer {access_token}'},
                json={"url": webhook_url, "event": "contact_added"}
            )
            response.raise_for_status()

            # Save webhook URL
            cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                           (user_id, webhook_url))
            conn.commit()

            # Redirect back to settings
            return redirect('/settings')
    except Exception as e:
        logger.error(f"Apollo.io authorization failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/authorize-seamless', methods=['GET'])
@token_required
def authorize_seamless(user_id):
    # Redirect to Seamless.AI OAuth URL (simplified for demo; in production, use proper OAuth flow)
    seamless_client_id = os.getenv('SEAMLESS_CLIENT_ID', 'your_client_id')
    redirect_uri = 'http://localhost:8000/seamless-callback'
    seamless_auth_url = f"https://login.seamless.ai/oauth/authorize?client_id={seamless_client_id}&redirect_uri={redirect_uri}&response_type=code"
    return redirect(seamless_auth_url)

@app.route('/seamless-callback', methods=['GET'])
@token_required
def seamless_callback(user_id):
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not found"}), 400

    # Exchange code for access token
    seamless_client_id = os.getenv('SEAMLESS_CLIENT_ID', 'your_client_id')
    seamless_client_secret = os.getenv('SEAMLESS_CLIENT_SECRET', 'your_client_secret')
    redirect_uri = 'http://localhost:8000/seamless-callback'

    try:
        with httpx.Client() as client:
            response = client.post(
                "https://login.seamless.ai/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": seamless_client_id,
                    "client_secret": seamless_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code
                }
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get('access_token')

            # Save the token
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, "seamless", access_token))
            conn.commit()

            # Register webhook for Seamless.AI
            webhook_url = f"http://your-app-url/webhook/seamless?user_id={user_id}"
            response = client.post(
                "https://api.seamless.ai/v1/webhooks",
                headers={'Authorization': f'Bearer {access_token}'},
                json={"url": webhook_url, "event": "contact_added"}
            )
            response.raise_for_status()

            # Save webhook URL
            cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                           (user_id, webhook_url))
            conn.commit()

            # Redirect back to settings
            return redirect('/settings')
    except Exception as e:
        logger.error(f"Seamless.AI authorization failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/authorize-zoominfo', methods=['GET'])
@token_required
def authorize_zoominfo(user_id):
    # Redirect to ZoomInfo OAuth URL (simplified for demo; in production, use proper OAuth flow)
    zoominfo_client_id = os.getenv('ZOOMINFO_CLIENT_ID', 'your_client_id')
    redirect_uri = 'http://localhost:8000/zoominfo-callback'
    zoominfo_auth_url = f"https://api.zoominfo.com/oauth/authorize?client_id={zoominfo_client_id}&redirect_uri={redirect_uri}&response_type=code"
    return redirect(zoominfo_auth_url)

@app.route('/zoominfo-callback', methods=['GET'])
@token_required
def zoominfo_callback(user_id):
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code not found"}), 400

    # Exchange code for access token
    zoominfo_client_id = os.getenv('ZOOMINFO_CLIENT_ID', 'your_client_id')
    zoominfo_client_secret = os.getenv('ZOOMINFO_CLIENT_SECRET', 'your_client_secret')
    redirect_uri = 'http://localhost:8000/zoominfo-callback'

    try:
        with httpx.Client() as client:
            response = client.post(
                "https://api.zoominfo.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": zoominfo_client_id,
                    "client_secret": zoominfo_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code
                }
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get('access_token')

            # Save the token
            cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                           (user_id, "zoominfo", access_token))
            conn.commit()

            # Register webhook for ZoomInfo
            webhook_url = f"http://your-app-url/webhook/zoominfo?user_id={user_id}"
            response = client.post(
                "https://api.zoominfo.com/v1/webhooks",
                headers={'Authorization': f'Bearer {access_token}'},
                json={"url": webhook_url, "event": "contact_added"}
            )
            response.raise_for_status()

            # Save webhook URL
            cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                           (user_id, webhook_url))
            conn.commit()

            # Redirect back to settings
            return redirect('/settings')
    except Exception as e:
        logger.error(f"ZoomInfo authorization failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/realnex-groups', methods=['GET'])
@token_required
def get_realnex_groups(user_id):
    realnex_token = utils.get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return jsonify({"error": "No RealNex token found"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.realnex.com/v1/groups",
                headers={'Authorization': f'Bearer {realnex_token}'}
            )
            response.raise_for_status()
            groups = response.json()
            return jsonify({"groups": [{"id": group["id"], "name": group["name"]} for group in groups]})
    except Exception as e:
        logger.error(f"Failed to fetch RealNex groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/mailchimp-groups', methods=['GET'])
@token_required
def get_mailchimp_groups(user_id):
    mailchimp_token = utils.get_token(user_id, "mailchimp", cursor)
    if not mailchimp_token:
        return jsonify({"error": "Not authorized with Mailchimp"}), 401

    try:
        with httpx.Client() as client:
            # Fetch audiences
            response = client.get(
                "https://us1.api.mailchimp.com/3.0/lists",
                auth=("anystring", mailchimp_token)
            )
            response.raise_for_status()
            audiences = response.json().get('lists', [])

            # Fetch interest categories (groups) for each audience
            groups = []
            for audience in audiences:
                audience_id = audience['id']
                response = client.get(
                    f"https://us1.api.mailchimp.com/3.0/lists/{audience_id}/interest-categories",
                    auth=("anystring", mailchimp_token)
                )
                response.raise_for_status()
                categories = response.json().get('categories', [])

                for category in categories:
                    category_id = category['id']
                    # Fetch interests (group names) within the category
                    response = client.get(
                        f"https://us1.api.mailchimp.com/3.0/lists/{audience_id}/interest-categories/{category_id}/interests",
                        auth=("anystring", mailchimp_token)
                    )
                    response.raise_for_status()
                    interests = response.json().get('interests', [])
                    for interest in interests:
                        groups.append({"id": interest['id'], "name": f"{category['title']} - {interest['name']}"})

            return jsonify({"groups": groups})
    except Exception as e:
        logger.error(f"Failed to fetch Mailchimp groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/constant-contact-groups', methods=['GET'])
@token_required
def get_constant_contact_groups(user_id):
    cc_token = utils.get_token(user_id, "constant_contact", cursor)
    if not cc_token:
        return jsonify({"error": "Not authorized with Constant Contact"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.cc.email/v3/contact_lists",
                headers={'Authorization': f'Bearer {cc_token}'}
            )
            response.raise_for_status()
            lists = response.json().get('lists', [])
            return jsonify({"groups": [{"id": lst['list_id'], "name": lst['name']} for lst in lists]})
    except Exception as e:
        logger.error(f"Failed to fetch Constant Contact groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/apollo-groups', methods=['GET'])
@token_required
def get_apollo_groups(user_id):
    apollo_token = utils.get_token(user_id, "apollo", cursor)
    if not apollo_token:
        return jsonify({"error": "Not authorized with Apollo.io"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.apollo.io/v1/lists",
                headers={'Authorization': f'Bearer {apollo_token}'}
            )
            response.raise_for_status()
            lists = response.json().get('lists', [])
            return jsonify({"groups": [{"id": lst['id'], "name": lst['name']} for lst in lists]})
    except Exception as e:
        logger.error(f"Failed to fetch Apollo.io groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/seamless-groups', methods=['GET'])
@token_required
def get_seamless_groups(user_id):
    seamless_token = utils.get_token(user_id, "seamless", cursor)
    if not seamless_token:
        return jsonify({"error": "Not authorized with Seamless.AI"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.seamless.ai/v1/lists",
                headers={'Authorization': f'Bearer {seamless_token}'}
            )
            response.raise_for_status()
            lists = response.json().get('lists', [])
            return jsonify({"groups": [{"id": lst['id'], "name": lst['name']} for lst in lists]})
    except Exception as e:
        logger.error(f"Failed to fetch Seamless.AI groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/zoominfo-groups', methods=['GET'])
@token_required
def get_zoominfo_groups(user_id):
    zoominfo_token = utils.get_token(user_id, "zoominfo", cursor)
    if not zoominfo_token:
        return jsonify({"error": "Not authorized with ZoomInfo"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.zoominfo.com/v1/lists",
                headers={'Authorization': f'Bearer {zoominfo_token}'}
            )
            response.raise_for_status()
            lists = response.json().get('lists', [])
            return jsonify({"groups": [{"id": lst['id'], "name": lst['name']} for lst in lists]})
    except Exception as e:
        logger.error(f"Failed to fetch ZoomInfo groups: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.json
    username = data.get('username')
    password = data.get('password')

    if username == 'admin' and password == 'password123':
        user_id = 'default'
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
    cache_key = f"dashboard_data:{user_id}"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logger.debug(f"Cache hit for {cache_key}")
            return jsonify(json.loads(cached_data))

    # Fetch contacts count from database
    cursor.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (user_id,))
    total_contacts = cursor.fetchone()[0]

    # Fetch duplicates count
    cursor.execute("SELECT COUNT(*) FROM duplicates_log WHERE user_id = ?", (user_id,))
    duplicates_detected = cursor.fetchone()[0]

    # Fetch recent deals from RealNex
    realnex_token = utils.get_token(user_id, "realnex", cursor)
    recent_deals = 0
    if realnex_token:
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/deals",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    params={"limit": 5}
                )
                response.raise_for_status()
                deals = response.json()
                recent_deals = len(deals)
        except Exception as e:
            logger.error(f"Failed to fetch RealNex deals: {e}")

    data = {
        "total_contacts": total_contacts,
        "recent_deals": recent_deals,
        "duplicates_detected": duplicates_detected
    }

    if redis_client:
        redis_client.setex(cache_key, 300, json.dumps(data))
        logger.debug(f"Cache set for {cache_key}")
    return jsonify(data)

@app.route('/sync-stats', methods=['GET'])
@token_required
def sync_stats(user_id):
    # Count sync actions from user_activity_log
    stats = {"local": 0, "apollo": 0, "seamless": 0, "zoominfo": 0}

    # Local contacts synced to RealNex
    cursor.execute("SELECT COUNT(*) FROM user_activity_log WHERE user_id = ? AND action = 'sync_realnex_contact' AND details NOT LIKE '%apollo_%' AND details NOT LIKE '%seamless_%' AND details NOT LIKE '%zoominfo_%'", (user_id,))
    stats["local"] = cursor.fetchone()[0]

    # Apollo.io contacts synced
    cursor.execute("SELECT COUNT(*) FROM user_activity_log WHERE user_id = ? AND action = 'sync_realnex_contact' AND details LIKE '%apollo_%'", (user_id,))
    stats["apollo"] = cursor.fetchone()[0]

    # Seamless.AI contacts synced
    cursor.execute("SELECT COUNT(*) FROM user_activity_log WHERE user_id = ? AND action = 'sync_realnex_contact' AND details LIKE '%seamless_%'", (user_id,))
    stats["seamless"] = cursor.fetchone()[0]

    # ZoomInfo contacts synced
    cursor.execute("SELECT COUNT(*) FROM user_activity_log WHERE user_id = ? AND action = 'sync_realnex_contact' AND details LIKE '%zoominfo_%'", (user_id,))
    stats["zoominfo"] = cursor.fetchone()[0]

    return jsonify(stats)

@app.route('/import-stats', methods=['GET'])
@token_required
def import_stats(user_id):
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
    cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp",
                   (user_id,))
    messages = cursor.fetchall()
    result = [{"sender": msg[0], "message": msg[1], "timestamp": msg[2]} for msg in messages]
    return jsonify({"messages": result})

# Activity log endpoint
@app.route('/activity_log', methods=['GET'])
@token_required
def get_activity_log(user_id):
    cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
    logs = cursor.fetchall()
    result = [{"action": log[0], "details": json.loads(log[1]), "timestamp": log[2]} for log in logs]
    return jsonify({"activity_log": result})

# Health history endpoint
@app.route('/health-history', methods=['GET'])
@token_required
def get_health_history(user_id):
    cursor.execute("SELECT contact_id, email_health_score, phone_health_score, timestamp FROM health_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
    history = cursor.fetchall()
    result = [{"contact_id": h[0], "email_health_score": h[1], "phone_health_score": h[2], "timestamp": h[3]} for h in history]
    return jsonify({"health_history": result})

# Duplicates endpoint
@app.route('/duplicates', methods=['GET'])
@token_required
def get_duplicates(user_id):
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
    return jsonify({"status": "
