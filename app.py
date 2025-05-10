import os
import json
import logging
import requests
import pandas as pd
import tempfile
import openai
from flask import Flask, request, jsonify, send_from_directory, render_template
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
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

DEFAULT_CAMPAIGN_MODE = os.getenv("DEFAULT_CAMPAIGN_MODE", "realnex")
UNLOCK_EMAIL_PROVIDER_SELECTION = os.getenv("UNLOCK_EMAIL_PROVIDER_SELECTION", "false").lower() == "true"

TERMS_MESSAGE = (
    "Protection of data is paramount to RealNex. By uploading data, you agree to the RealNex Terms of Use "
    "(https://realnex.com/Terms). You represent you own the data or have the right to use it, and agree to "
    "indemnify RealNex for any claims from misuse.")

@app.route("/terms-message", methods=["GET"])
def get_terms_message():
    return jsonify({"message": TERMS_MESSAGE})

@app.route("/accept-terms", methods=["POST"])
def accept_terms():
    accepted = request.json.get("accepted")
    user = request.json.get("user", "anonymous")
    if accepted:
        logging.info(f"User {user} accepted terms at {datetime.utcnow().isoformat()} UTC")
        return jsonify({"accepted": True})
    else:
        return jsonify({"accepted": False, "error": "Terms must be accepted before importing."}), 403

@app.route("/upload-check", methods=["POST"])
def check_before_upload():
    data = request.json
    if not data.get("accepted_terms"):
        return jsonify({"error": "You must accept the RealNex Terms before uploading."}), 403
    return jsonify({"ok": True})

@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        token = request.form.get("token")
        file = request.files.get("file")
        notes = request.form.get("notes", "")
        accepted_terms = request.form.get("accepted_terms", "false") == "true"

        if not accepted_terms:
            return jsonify({"error": "Terms must be accepted before uploading."}), 403

        if not file or not token:
            return jsonify({"error": "Missing file or token."}), 400

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        if filename.endswith('.xlsx'):
            df = pd.read_excel(file_path)
            mapping = suggest_field_mapping(df.columns.tolist())
            return jsonify({"mappingSuggested": mapping})

        elif filename.endswith('.pdf'):
            text = extract_text_from_pdf(file_path)
        else:
            text = extract_text_from_image(file_path)

        if is_business_card(text):
            parsed = parse_ocr_text(text)
            location = extract_exif_location(file_path)
            contact = {
                "fullName": parsed.get("fullName"),
                "email": parsed.get("email"),
                "work": parsed.get("work"),
                "company": parsed.get("company"),
                "prospect": True
            }
            if location:
                contact.update(location)

            status, result = realnex_post("/Crm/contact", token, contact)
            if status in [200, 201]:
                create_history(token, "Business Card Import", notes, object_key=result.get("key"), object_type="contact")
                return jsonify({"message": "Business card imported successfully.", "contact": contact})
            else:
                return jsonify({"error": result}), 500
        else:
            return jsonify({"message": "Text extracted, but no business card detected.", "text": text})
    except Exception as e:
        logging.error(f"Upload processing failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/docs")
def swagger_ui():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
      <title>Goose & Maverick API Docs</title>
      <link rel="stylesheet" type="text/css" href="/static/swagger-ui.css" />
      <script src="/static/swagger-ui-bundle.js"></script>
      <script src="/static/swagger-ui-standalone-preset.js"></script>
    </head>
    <body>
      <div id="swagger-ui"></div>
      <script>
        const ui = SwaggerUIBundle({
          url: "/static/openapi.json",
          dom_id: '#swagger-ui',
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: "StandaloneLayout"
        })
      </script>
    </body>
    </html>
    '''

# === Campaign Sync Logic ===
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
        return True
