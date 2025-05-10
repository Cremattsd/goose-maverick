import os
import json
import logging
import requests
import pandas as pd
import tempfile
import openai
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
openai.api_key = os.getenv("OPENAI_API_KEY")

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")

CONSTANT_CONTACT_API_KEY = os.getenv("CONSTANT_CONTACT_API_KEY")
CONSTANT_CONTACT_ACCESS_TOKEN = os.getenv("CONSTANT_CONTACT_ACCESS_TOKEN")
CONSTANT_CONTACT_LIST_ID = os.getenv("CONSTANT_CONTACT_LIST_ID")

DEFAULT_CAMPAIGN_MODE = os.getenv("DEFAULT_CAMPAIGN_MODE", "realnex")  # 'realnex' | 'mailchimp' | 'constant_contact'

# Hidden feature toggle (unlocked by admin only)
UNLOCK_EMAIL_PROVIDER_SELECTION = os.getenv("UNLOCK_EMAIL_PROVIDER_SELECTION", "false").lower() == "true"


def sync_to_mailchimp(email, first_name="", last_name=""):
    try:
        url = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0/lists/{MAILCHIMP_LIST_ID}/members"
        data = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {
                "FNAME": first_name,
                "LNAME": last_name
            }
        }
        headers = {
            "Authorization": f"Bearer {MAILCHIMP_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.post(url, headers=headers, json=data)
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Mailchimp sync failed: {str(e)}")
        return False

def sync_to_constant_contact(email, first_name="", last_name=""):
    try:
        headers = {
            "Authorization": f"Bearer {CONSTANT_CONTACT_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = {
            "email_address": {"address": email},
            "first_name": first_name,
            "last_name": last_name,
            "list_memberships": [CONSTANT_CONTACT_LIST_ID]
        }
        url = "https://api.cc.email/v3/contacts/sign_up_form"
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Constant Contact sync failed: {str(e)}")
        return False

def sync_contact(email, first_name, last_name, provider=None):
    provider = provider or DEFAULT_CAMPAIGN_MODE
    if not UNLOCK_EMAIL_PROVIDER_SELECTION:
        provider = DEFAULT_CAMPAIGN_MODE
    if provider == "mailchimp":
        return sync_to_mailchimp(email, first_name, last_name)
    elif provider == "constant_contact":
        return sync_to_constant_contact(email, first_name, last_name)
    else:
        logging.info(f"Using internal RealNex campaign sync for {email}")
        return True  # Replace with actual internal sync logic when implemented

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_post(endpoint, token, data):
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
        response.raise_for_status()
        return response.status_code, response.json() if response.content else {}
    except requests.RequestException as e:
        logging.error(f"RealNex POST failed: {str(e)}")
        return 500, {"error": f"API request failed: {str(e)}"}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_get(endpoint, token):
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
        response.raise_for_status()
        return response.status_code, response.json().get('value', [])
    except requests.RequestException as e:
        logging.error(f"RealNex GET failed: {str(e)}")
        return 500, {"error": f"API request failed: {str(e)}"}

def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    status, result = realnex_post("/Crm/history", token, payload)
    if status not in [200, 201]:
        logging.error(f"Failed to create history: {result}")
    return status, result

@app.route('/')
def index():
    try:
        return app.send_static_file('index.html')
    except Exception as e:
        logging.error(f"Failed to serve index.html: {str(e)}")
        return jsonify({"error": "Failed to load frontend"}), 500

@app.route('/sync-to-mailchimp', methods=['POST'])
def sync_mailchimp():
    try:
        data = request.json
        email = data.get("email")
        first = data.get("firstName", "")
        last = data.get("lastName", "")
        if not email:
            return jsonify({"error": "Email is required"}), 400
        success = sync_to_mailchimp(email, first, last)
        return jsonify({"success": success})
    except Exception as e:
        logging.error(f"Mailchimp sync error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/sync-to-constant-contact', methods=['POST'])
def sync_constant_contact():
    try:
        data = request.json
        email = data.get("email")
        first = data.get("firstName", "")
        last = data.get("lastName", "")
        if not email:
            return jsonify({"error": "Email is required"}), 400
        success = sync_to_constant_contact(email, first, last)
        return jsonify({"success": success})
    except Exception as e:
        logging.error(f"Constant Contact sync error: {str(e)}")
        return jsonify({"error": str(e)}), 500
