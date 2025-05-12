import os
import json
import logging
import requests
import pandas as pd
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")

CONSTANT_CONTACT_API_KEY = os.getenv("CONSTANT_CONTACT_API_KEY")
CONSTANT_CONTACT_ACCESS_TOKEN = os.getenv("CONSTANT_CONTACT_ACCESS_TOKEN")
CONSTANT_CONTACT_LIST_ID = os.getenv("CONSTANT_CONTACT_LIST_ID")

DEFAULT_CAMPAIGN_MODE = os.getenv("DEFAULT_CAMPAIGN_MODE", "realnex")
UNLOCK_EMAIL_PROVIDER_SELECTION = os.getenv("UNLOCK_EMAIL_PROVIDER_SELECTION", "false").lower() == "true"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    response.raise_for_status()
    return response.status_code, response.json() if response.content else {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_get(endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.status_code, response.json().get('value', [])

def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    return realnex_post("/Crm/history", token, payload)

def sync_to_mailchimp(email, first_name="", last_name=""):
    try:
        url = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0/lists/{MAILCHIMP_LIST_ID}/members"
        data = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {"FNAME": first_name, "LNAME": last_name}
        }
        headers = {"Authorization": f"Bearer {MAILCHIMP_API_KEY}", "Content-Type": "application/json"}
        requests.post(url, headers=headers, json=data).raise_for_status()
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
        requests.post(url, headers=headers, json=data).raise_for_status()
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
    logging.info(f"Using internal RealNex campaign sync for {email}")
    return True

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        system_prompt = (
            "Hi! I’m Maverick, your chat assistant. Ask me anything about RealNex and RealNex VR or RealNex Real Blasts & Campaigns. "
            "I also have access to the RealNex knowledge base for many questions and more!"
        )

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )

        answer = response.choices[0].message.content
        logging.info(f"User asked: {user_message}, Answered: {answer}")
        return jsonify({"answer": answer})
    except Exception as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500

@app.route('/validate-token', methods=['POST'])
def validate_token():
    try:
        token = request.json.get("token", "").strip()
        if not token:
            return jsonify({"error": "Token is required"}), 400

        status, result = realnex_get("Contacts?$top=1", token)
        if status == 200:
            return jsonify({"valid": True})
        return jsonify({"valid": False, "error": result.get("error", "Invalid token")}), 401
    except Exception as e:
        logging.error(f"Error validating token: {str(e)}")
        return jsonify({"error": f"Error validating token: {str(e)}"}), 500

@app.route('/terms', methods=['GET'])
def get_terms():
    return jsonify({
        "text": (
            "Protection of data is paramount to RealNex. By using the RealNex Services, you agree to abide by the Terms of Use. "
            "You represent that you are the owner of all data uploaded and have legal authority to upload it."
        )
    })

@app.route('/sync-to-mailchimp', methods=['POST'])
def sync_mailchimp():
    data = request.json
    success = sync_to_mailchimp(data.get("email"), data.get("firstName", ""), data.get("lastName", ""))
    return jsonify({"success": success})

@app.route('/sync-to-constant-contact', methods=['POST'])
def sync_constant_contact():
    data = request.json
    success = sync_to_constant_contact(data.get("email"), data.get("firstName", ""), data.get("lastName", ""))
    return jsonify({"success": success})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))