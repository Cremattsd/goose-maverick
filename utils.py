import os
import json
import logging
import hashlib
import redis
import httpx
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
from fuzzywuzzy import fuzz

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

def hash_entity(entity, entity_type):
    """Generate a unique hash for an entity based on its type and key fields."""
    if entity_type == "contact":
        key_fields = f"{entity.get('name', '')}{entity.get('email', '')}".lower()
    elif entity_type == "company":
        key_fields = f"{entity.get('name', '')}{entity.get('address', '')}".lower()
    elif entity_type == "property":
        key_fields = f"{entity.get('address', '')}{entity.get('city', '')}{entity.get('zip', '')}".lower()
    elif entity_type == "space":
        key_fields = f"{entity.get('property_id', '')}{entity.get('space_number', '')}".lower()
    else:
        raise ValueError(f"Unsupported entity type: {entity_type}")
    
    return hashlib.sha256(key_fields.encode('utf-8')).hexdigest()

def hash_contact(contact):
    """Generate a hash of a contact's key fields to detect duplicates."""
    key_fields = f"{contact.get('Email', '')}{contact.get('Full Name', '')}{contact.get('Work Phone', '')}"
    return hashlib.sha256(key_fields.encode()).hexdigest()

def is_near_duplicate(new_data, existing_data, threshold=90):
    """Check if two entities are near duplicates using fuzzy matching."""
    new_str = json.dumps(new_data, sort_keys=True)
    existing_str = json.dumps(existing_data, sort_keys=True)
    similarity = fuzz.ratio(new_str.lower(), existing_str.lower())
    return similarity >= threshold

def log_duplicate(user_id, entity, entity_type, cursor, conn):
    """Log a duplicate entity in the duplicates_log table."""
    # Use hash_contact for contacts for backward compatibility, hash_entity for others
    entity_hash = hash_contact(entity) if entity_type == "contact" else hash_entity(entity, entity_type)
    timestamp = datetime.now().isoformat()
    
    # Check for near duplicates in the database
    cursor.execute("SELECT contact_data FROM duplicates_log WHERE user_id = ? AND contact_hash LIKE ?",
                   (user_id, f"{entity_type}%"))
    existing_entries = cursor.fetchall()
    for entry in existing_entries:
        existing_data = json.loads(entry[0])
        if is_near_duplicate(entity, existing_data):
            logger.info(f"Near-duplicate {entity_type} detected for user {user_id}: {entity}")
            break
    else:
        cursor.execute("INSERT INTO duplicates_log (user_id, contact_hash, contact_data, timestamp) VALUES (?, ?, ?, ?)",
                       (user_id, entity_hash, json.dumps({**entity, "entity_type": entity_type}), timestamp))
        conn.commit()
        logger.info(f"Logged duplicate {entity_type} for user {user_id}: {entity_hash}")
    
    log_user_activity(user_id, "log_duplicate", {"contact_hash": entity_hash}, cursor, conn)

def log_user_activity(user_id, action, details, cursor, conn):
    """Log user activity for auditing and analytics."""
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, action, json.dumps(details), timestamp))
    conn.commit()
    logger.info(f"Logged activity for user {user_id}: {action} - {details}")

def get_user_settings(user_id, cursor, conn):
    """Retrieve user settings from the database or return defaults."""
    cursor.execute("SELECT language, subject_generator_enabled, deal_alerts_enabled, email_notifications, sms_notifications, mailchimp_group_id, constant_contact_group_id, realnex_group_id, apollo_group_id, seamless_group_id, zoominfo_group_id FROM user_settings WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        return {
            "language": result[0],
            "subject_generator_enabled": bool(result[1]),
            "deal_alerts_enabled": bool(result[2]),
            "email_notifications": bool(result[3]),
            "sms_notifications": bool(result[4]),
            "mailchimp_group_id": result[5],
            "constant_contact_group_id": result[6],
            "realnex_group_id": result[7],
            "apollo_group_id": result[8],
            "seamless_group_id": result[9],
            "zoominfo_group_id": result[10]
        }
    default_settings = {
        "language": "en",
        "subject_generator_enabled": True,
        "deal_alerts_enabled": True,
        "email_notifications": True,
        "sms_notifications": True,
        "mailchimp_group_id": "",
        "constant_contact_group_id": "",
        "realnex_group_id": "",
        "apollo_group_id": "",
        "seamless_group_id": "",
        "zoominfo_group_id": ""
    }
    cursor.execute("""
        INSERT INTO user_settings 
        (user_id, language, subject_generator_enabled, deal_alerts_enabled, email_notifications, sms_notifications, 
         mailchimp_group_id, constant_contact_group_id, realnex_group_id, apollo_group_id, seamless_group_id, zoominfo_group_id) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, default_settings["language"], 1, 1, 1, 1, "", "", "", "", "", ""))
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

def get_users(user_id, cursor):
    """Mock function to get users (replace with actual implementation)."""
    return [{"userId": user_id, "userName": "CRE Pro"}]

def search_realnex_entities(user_id, entity_type, query_params, cursor):
    """Search RealNex for entities to avoid duplicates."""
    realnex_token = get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return []

    try:
        with httpx.Client() as client:
            response = client.get(
                f"https://sync.realnex.com/api/v1/Crm/{entity_type}",
                headers={'Authorization': f'Bearer {realnex_token}'},
                params=query_params
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to search RealNex for {entity_type}: {e}")
        return []

def get_field_mappings(user_id, entity_type, cursor):
    """Mock function to get field mappings (replace with actual implementation)."""
    return {
        "name": "Name:",
        "address": "Address:",
        "city": "City:",
        "zip": "Zip:",
        "space_number": "Space Number:",
        "project": "Project:"
    }

def log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn):
    """Log email and phone health scores in the health_history table."""
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO health_history (user_id, contact_id, email_health_score, phone_health_score, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (user_id, contact_id, email_score, phone_score, timestamp))
    conn.commit()

def log_change(user_id, entity_type, entity_id, change_type, details, cursor, conn):
    """Log a change for RealNex sync."""
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, f"{change_type}_{entity_type}", json.dumps({**details, "entity_id": entity_id}), datetime.now().isoformat()))
    conn.commit()

def sync_changes_to_realnex(user_id, cursor, conn):
    """Sync changes to RealNex (simplified)."""
    logger.info(f"Synced changes to RealNex for user {user_id}")

def validate_realnex_token(token):
    """Validate a RealNex API token by making a test request."""
    try:
        with httpx.Client() as client:
            response = client.get(
                "https://sync.realnex.com/api/v1/Crm/contact",
                headers={'Authorization': f'Bearer {token}'},
                params={"$top": 1}
            )
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"RealNex token validation failed: {e}")
        return False

def send_2fa_code(user_id, twilio_client, cursor, conn):
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
