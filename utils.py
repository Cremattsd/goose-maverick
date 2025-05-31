import os
import json
import re
import smtplib
import logging
import base64
import hashlib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import redis
import jwt
import httpx
from twilio.rest import Client as TwilioClient
from fpdf import FPDF
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO

from config import *

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

# Redis setup
redis_client = None

def load_ca_cert():
    """Load the Redis CA certificate from file or environment variable."""
    ca_path = REDIS_CA_PATH
    if os.path.exists(ca_path):
        return ca_path
    ca_cert = os.getenv('REDIS_CA_CERT')
    if ca_cert:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem') as temp_file:
            temp_file.write(ca_cert.encode())
            return temp_file.name
    raise FileNotFoundError("Redis CA certificate not found in file or environment variable.")

def init_redis():
    """Initialize Redis connection lazily."""
    global redis_client
    if redis_client is not None:
        return redis_client
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            username=REDIS_USERNAME,
            password=REDIS_PASSWORD,
            decode_responses=True,
            ssl=True,
            ssl_ca_certs=load_ca_cert()
        )
        redis_client.ping()
        logger.info("Redis connection established successfully.")
        return redis_client
    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {e}. Ensure Redis is running.")
        redis_client = None
        return None

# Initialize Twilio client
try:
    twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
    logger.info("Twilio client initialized successfully.")
except Exception as e:
    logger.error(f"Twilio client initialization failed: {e}")
    twilio_client = None

def log_user_activity(user_id, action, details, cursor, conn):
    """Log user activity for auditing and analytics."""
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, action, json.dumps(details), timestamp))
    conn.commit()
    logger.info(f"Logged activity for user {user_id}: {action} - {details}")

def get_user_settings(user_id, cursor, conn):
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

def get_token(user_id, service, cursor):
    """Retrieve a token from Redis or the database, with caching."""
    cache_key = f"token:{user_id}:{service}"
    redis = init_redis()
    if redis:
        token = redis.get(cache_key)
        if token:
            logger.debug(f"Token for {user_id}:{service} retrieved from Redis cache.")
            return token
    cursor.execute("SELECT token FROM user_tokens WHERE user_id = ? AND service = ?", (user_id, service))
    result = cursor.fetchone()
    if result:
        token = result[0]
        if redis:
            redis.setex(cache_key, 3600, token)
            logger.debug(f"Token for {user_id}:{service} cached in Redis.")
        return token
    logger.warning(f"No token found for {user_id}:{service}.")
    return None

def award_points(user_id, points, reason, cursor, conn):
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
    log_user_activity(user_id, "award_points", {"points": points, "reason": reason}, cursor, conn)
    return new_points, email_credits, has_msa, points_message

def update_onboarding(user_id, step, cursor, conn):
    """Mark an onboarding step as completed for a user."""
    cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, 1)", (user_id, step))
    conn.commit()
    log_user_activity(user_id, "update_onboarding", {"step": step}, cursor, conn)

async def get_realnex_data(user_id, endpoint, cursor):
    """Fetch data from the RealNex API for a given endpoint."""
    token = get_token(user_id, "realnex", cursor)
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

def send_2fa_code(user_id, cursor, conn):
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
        log_user_activity(user_id, "send_2fa_code", {"code": code}, cursor, conn)
        return True
    except Exception as e:
        logger.error(f"Failed to send 2FA code: {e}")
        return False

def check_2fa(user_id, code, cursor, conn):
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
        log_user_activity(user_id, "check_2fa", {"status": "success"}, cursor, conn)
        return True
    log_user_activity(user_id, "check_2fa", {"status": "failed"}, cursor, conn)
    return False

def hash_contact(contact):
    """Generate a hash of a contact's key fields to detect duplicates."""
    key_fields = f"{contact.get('Email', '')}{contact.get('Full Name', '')}{contact.get('Work Phone', '')}"
    return hashlib.sha256(key_fields.encode()).hexdigest()

def log_duplicate(user_id, contact, cursor, conn):
    """Log a duplicate contact in the database."""
    contact_hash = hash_contact(contact)
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO duplicates_log (user_id, contact_hash, contact_data, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, contact_hash, json.dumps(contact), timestamp))
    conn.commit()
    log_user_activity(user_id, "log_duplicate", {"contact_hash": contact_hash}, cursor, conn)

def generate_pdf_report(user_id, data, report_title, cursor, conn):
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

def generate_deal_trend_chart(user_id, historical_data, deal_type, cursor, conn):
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
