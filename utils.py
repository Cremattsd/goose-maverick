import hashlib
import json
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import httpx
from mailchimp_marketing import Client as MailchimpClient
from mailchimp_marketing.api_client import ApiClientError
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from config import *

# Initialize Mailchimp client
mailchimp_client = MailchimpClient()
if MAILCHIMP_API_KEY:
    mailchimp_client.set_config({
        "api_key": MAILCHIMP_API_KEY,
        "server": MAILCHIMP_SERVER_PREFIX
    })

# Configure logging (in case we need to use it directly here)
logger = logging.getLogger(__name__)

def hash_entity(data, entity_type):
    """Hash an entity to check for duplicates—like a CRE detective finding double leases! 🕵️"""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

def get_user_settings(user_id, cursor, conn):
    """Fetch user settings from the database—know your CRE client like a pro! 🏢"""
    cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        return {
            "language": result[1],
            "subject_generator_enabled": bool(result[2]),
            "deal_alerts_enabled": bool(result[3]),
            "email_notifications": bool(result[4]),
            "sms_notifications": bool(result[5]),
            "mailchimp_group_id": result[6],
            "constant_contact_group_id": result[7],
            "realnex_group_id": result[8],
            "apollo_group_id": result[9],
            "seamless_group_id": result[10],
            "zoominfo_group_id": result[11]
        }
    # Default settings if none exist
    return {
        "language": "en",
        "subject_generator_enabled": False,
        "deal_alerts_enabled": False,
        "email_notifications": False,
        "sms_notifications": False,
        "mailchimp_group_id": "",
        "constant_contact_group_id": "",
        "realnex_group_id": "",
        "apollo_group_id": "",
        "seamless_group_id": "",
        "zoominfo_group_id": ""
    }

def get_users(user_id, cursor):
    """Fetch users from the database—find out who’s signing the CRE leases! 📜"""
    cursor.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
    users = [{"userId": row[0], "userName": row[1].split('@')[0] if row[1] else "Unknown"} for row in cursor.fetchall()]
    return users

def get_token(user_id, service, cursor):
    """Fetch a service token for a user—like getting the keys to a CRE building! 🔑"""
    cursor.execute("SELECT token FROM user_tokens WHERE user_id = ? AND service = ?", (user_id, service))
    result = cursor.fetchone()
    return result[0] if result else None

def log_duplicate(user_id, entity_data, entity_type, cursor, conn):
    """Log duplicate entities—like a CRE manager spotting double-booked tenants! 🧹"""
    contact_hash = hash_entity(entity_data, entity_type)
    cursor.execute("INSERT INTO duplicates_log (user_id, contact_hash, contact_data, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, contact_hash, json.dumps(entity_data), datetime.now().isoformat()))
    conn.commit()
    logger.info(f"Duplicate {entity_type} logged for user {user_id}: hash={contact_hash}")

def log_user_activity(user_id, action, details, cursor, conn):
    """Log user activity—like keeping a CRE deal journal! 📝"""
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, action, json.dumps(details), datetime.now().isoformat()))
    conn.commit()
    logger.info(f"Activity logged for user {user_id}: action={action}")

def log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn):
    """Log contact health history—keep your CRE contacts in check! 🩺"""
    cursor.execute("INSERT INTO health_history (user_id, contact_id, email_health_score, phone_health_score, timestamp) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (user_id, contact_id, email_score, phone_score, datetime.now().isoformat()))
    conn.commit()
    logger.info(f"Health history logged for user {user_id}, contact {contact_id}: email_score={email_score}, phone_score={phone_score}")

def log_change(user_id, entity_type, entity_id, change_type, change_data, cursor, conn):
    """Log changes to RealNex entities—like a CRE audit trail! 📊"""
    # This could be expanded to log changes in a separate table if needed
    log_user_activity(user_id, f"{change_type}_{entity_type}", {
        "entity_id": entity_id,
        "change_data": change_data
    }, cursor, conn)

def search_realnex_entities(user_id, entity_type, query_params, cursor):
    """Search RealNex for entities to avoid duplicates—like a CRE pro doing due diligence! 🔍"""
    token = get_token(user_id, "realnex", cursor)
    if not token:
        logger.warning(f"No RealNex token found for user {user_id}")
        return []

    try:
        with httpx.Client() as client:
            response = client.get(
                f"https://sync.realnex.com/api/v1/Crm/{entity_type}",
                headers={'Authorization': f'Bearer {token}'},
                params=query_params
            )
            response.raise_for_status()
            return response.json().get("value", [])
    except httpx.HTTPStatusError as e:
        logger.error(f"RealNex search failed for user {user_id}: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error during RealNex search for user {user_id}: {e}")
        return []

def sync_changes_to_realnex(user_id, cursor, conn):
    """Sync changes to RealNex—like sealing a CRE deal with a handshake! 🤝"""
    # Placeholder for syncing changes; implement as needed
    logger.info(f"Changes synced to RealNex for user {user_id}—everything’s up to date!")

def get_field_mappings(user_id, entity_type, cursor):
    """Fetch field mappings for RealNex syncing—like mapping out a CRE property! 🗺️"""
    # Placeholder: In a real app, this might fetch mappings from a table or API
    mappings = {
        "property": {
            "name": "Property Name:",
            "address": "Address:",
            "city": "City:",
            "zip": "Zip:"
        },
        "space": {
            "space_number": "Space Number:"
        },
        "company": {
            "name": "Company Name:",
            "address": "Address:"
        },
        "project": {
            "project": "Project Name:"
        },
        "leasecomp": {
            "suite": "Lease Suite:"
        },
        "salecomp": {
            "property_name": "Sale Property:"
        }
    }
    return mappings.get(entity_type, {})

def send_email(recipient, subject, body):
    """Send an email using SMTP—like mailing a CRE lease agreement! 📬"""
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = recipient

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipient, msg.as_string())
        logger.info(f"Email sent to {recipient}: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email to {recipient}: {e}")

def sync_to_mailchimp(user_id, contact_data, cursor, conn):
    """Sync a contact to Mailchimp—like adding a tenant to your CRE email list! 📧"""
    settings = get_user_settings(user_id, cursor, conn)
    list_id = settings.get("mailchimp_group_id")
    if not list_id:
        logger.warning(f"No Mailchimp list ID configured for user {user_id}")
        return

    email = contact_data.get("email")
    if not email:
        logger.warning(f"No email provided for Mailchimp sync for user {user_id}")
        return

    try:
        member_info = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {
                "FNAME": contact_data.get("name", "").split(' ')[0] if contact_data.get("name") else "",
                "LNAME": ' '.join(contact_data.get("name", "").split(' ')[1:]) if contact_data.get("name") and len(contact_data.get("name").split(' ')) > 1 else ""
            }
        }
        mailchimp_client.lists.add_list_member(list_id, member_info)
        logger.info(f"Contact {email} synced to Mailchimp for user {user_id}")
    except ApiClientError as e:
        logger.error(f"Failed to sync contact to Mailchimp for user {user_id}: {e.text}")

def generate_deal_trend_chart(deals, deal_type):
    """Generate a chart for deal trends—like graphing a CRE market boom! 📈"""
    if not deals:
        return {}

    # Extract data for plotting
    dates = [deal['date'] for deal in deals]
    if deal_type == "LeaseComp":
        values = [deal['rent_month'] for deal in deals]
        ylabel = "Rent per Month ($)"
    else:  # SaleComp
        values = [deal['sale_price'] for deal in deals]
        ylabel = "Sale Price ($)"

    # Create the plot
    plt.figure(figsize=(10, 5))
    plt.plot(dates, values, marker='o')
    plt.title(f"{deal_type} Trends Over Time")
    plt.xlabel("Date")
    plt.ylabel(ylabel)
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Save plot to a BytesIO object and encode as base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    image_png = buffer.getvalue()
    buffer.close()
    plt.close()

    # Encode image to base64 for JSON response
    image_base64 = base64.b64encode(image_png).decode('utf-8')
    return {
        "image": f"data:image/png;base64,{image_base64}",
        "dates": dates,
        "values": values,
        "ylabel": ylabel
    }
