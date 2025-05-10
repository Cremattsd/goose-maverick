import os
import logging
import requests
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure logging
logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize services
REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Validate OpenAI API key
if not client.api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

# === RealNex API Helpers ===
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

# === Routes ===
@app.route('/')
def index():
    try:
        return app.send_static_file('index.html')
    except Exception as e:
        logging.error(f"Failed to serve index.html: {str(e)}")
        return jsonify({"error": "Failed to load frontend"}), 500

@app.route('/validate-token', methods=['POST'])
def validate_token():
    try:
        token = request.json.get('token', '').strip()
        if not token:
            return jsonify({"error": "Missing token"}), 400

        status, result = realnex_get("Contacts", token)
        if status == 200:
            return jsonify({"valid": True})
        else:
            return jsonify({"valid": False, "error": result.get("error", "Invalid token")}), 401
    except Exception as e:
        logging.error(f"Token validation failed: {str(e)}")
        return jsonify({"error": f"Validation failed: {str(e)}"}), 500

@app.route('/suggest-mapping', methods=['POST'])
def suggest_mapping():
    file = request.files.get('file') if request.files else None
    if not file or not file.filename.lower().endswith('.xlsx'):
        return jsonify({"error": "Invalid file type, only XLSX allowed"}), 400

    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix='.xlsx') as temp_file:
            file.save(temp_file.name)
            df = pd.read_excel(temp_file.name)
        suggested_mapping = suggest_field_mapping(df)
        return jsonify({"suggestedMapping": suggested_mapping})
    except Exception as e:
        logging.error(f"Field mapping suggestion failed: {str(e)}")
        return jsonify({"error": f"Mapping suggestion failed: {str(e)}"}), 500

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        system_prompt = (
            "You are Maverick, an expert assistant focused on commercial real estate, RealNex, Pix-Virtual, and ViewLabs. "
            "Always greet on first message, stay on-topic, and politely deflect anything unrelated."
        )

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4-turbo"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        answer = response.choices[0].message.content
        logging.info(f"User asked: {user_message}, Answered: {answer}")
        return jsonify({"answer": answer})
    except openai.OpenAIError as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error in /ask: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/upload-business-card', methods=['POST'])
def upload_business_card():
    token = request.form.get('token') or request.json.get('token')
    notes = request.form.get('notes', '').strip() if request.form else ''
    file = request.files.get('file') if request.files else None

    if not file or not token:
        return jsonify({"error": "Missing file or token."}), 400

    if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
        return jsonify({"error": "Invalid file type, only PNG/JPG/PDF allowed"}), 400

    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf' if file.filename.endswith('.pdf') else '.jpg') as temp_file:
            file.save(temp_file.name)
            if file.filename.endswith('.pdf'):
                text = extract_text_from_pdf(temp_file.name)
                exif = None
            else:
                text = extract_text_from_image(temp_file.name)
                exif = extract_exif_location(temp_file.name)

        if not text:
            return jsonify({"error": "No text extracted from file"}), 400

        parsed = parse_ocr_text(text)
        contact = {
            "fullName": parsed["fullName"],
            "email": parsed["email"],
            "work": parsed["work"],
            "prospect": True
        }
        if is_business_card(text) and notes:
            contact["notes"] = notes

        status, result = realnex_post("/Crm/contact", token, contact)
        if status not in [200, 201]:
            logging.error(f"Failed to create contact: {result}")
            return jsonify({"error": "Failed to create contact", "details": result}), 500

        key = result.get("key")
        msg = f"Imported via Goose\n\nOCR:\n{text}\n\nNotes:\n{notes}"
        create_history(token, "Goose Import", msg, key)

        if parsed["company"]:
            company = {"name": parsed["company"]}
            status, company_result = realnex_post("/Crm/company", token, company)
            if status in [200, 201]:
                company_key = company_result.get("key")
                create_history(token, "Goose Company Import", f"Company created: {parsed['company']}", company_key, "company")

        draft = f"Subject: Great connecting!\n\nHi {parsed['fullName'].split()[0] if parsed['fullName'] else 'there'},\n\nAdded you to my CRM — let me know how I can help.\n\nBest,\nMatty"
        logging.info(f"Processed card: email={parsed['email']}, status={status}")
        return jsonify({
            "parsedFields": parsed,
            "location": exif,
            "contactCreated": result,
            "status": status,
            "followUpEmail": draft
        })
    except Exception as e:
        logging.error(f"Business card processing failed: {str(e)}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

@app.route('/bulk-import', methods=['POST'])
def bulk_import():
    token = request.form.get('token') or request.json.get('token')
    file = request.files.get('file') if request.files else None
    mapping = request.form.get('mapping') or request.json.get('mapping', {})

    if not file or not token or not mapping:
        return jsonify({"error": "Missing file, token, or mapping."}), 400

    if not file.filename.lower().endswith('.xlsx'):
        return jsonify({"error": "Invalid file type, only XLSX allowed"}), 400

    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix='.xlsx') as temp_file:
            file.save(temp_file.name)
            df = pd.read_excel(temp_file.name)

        mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
        results = {"contacts": [], "companies": [], "properties": [], "spaces": [], "projects": []}
        for _, row in df.iterrows():
            row_data = row.to_dict()
            for entity, fields in mapping.items():
                mapped_data = map_fields(row_data, fields)
                if mapped_data:
                    status, result = realnex_post(f"/Crm/{entity}", token, mapped_data)
                    if status in [200, 201]:
                        results[entity].append(result)
                        key = result.get("key")
                        create_history(token, f"Goose Bulk Import - {entity.capitalize()}", f"Imported {entity}: {mapped_data}", key, entity)
                    else:
                        logging.warning(f"Failed to import {entity}: {result}")

        logging.info(f"Bulk import completed: {len(df)} rows processed")
        return jsonify({"results": results, "processed": len(df)})
    except Exception as e:
        logging.error(f"Bulk import failed: {str(e)}")
        return jsonify({"error": f"Import failed: {str(e)}"}), 500

@app.route('/sync-followups', methods=['POST'])
def sync_followups():
    try:
        token = request.json.get('token')
        days = int(request.json.get('days', 30))
        if not token:
            return jsonify({"error": "Missing token"}), 400

        status, contacts = realnex_get("Contacts", token)
        if status != 200:
            logging.error(f"Failed to fetch contacts: {contacts}")
            return jsonify({"error": "Failed to fetch contacts", "details": contacts}), 500

        cutoff = datetime.now() - timedelta(days=days)
        stale = [c for c in contacts if not c.get('lastActivity') or datetime.fromisoformat(c['lastActivity']) < cutoff]

        status, group_resp = realnex_post("/Crm/contactgroup", token, {"name": "Follow Up Group"})
        if status not in [200, 201]:
            logging.error(f"Failed to create group: {group_resp}")
            return jsonify({"error": "Failed to create group", "details": group_resp}), 500

        group_id = group_resp.get("key")
        for c in stale:
            status, result = realnex_post("/Crm/contactgroupmember", token, {"contact_key": c['Key'], "group_key": group_id})
            if status not in [200, 201]:
                logging.warning(f"Failed to add contact {c['Key']} to group: {result}")

        logging.info(f"Synced {len(stale)} stale contacts to Follow Up Group")
        return jsonify({"matched": len(stale), "group_key": group_id})
    except Exception as e:
        logging.error(f"Sync followups failed: {str(e)}")
        return jsonify({"error": f"Sync failed: {str(e)}"}), 500

@app.route('/sync-mailchimp', methods=['POST'])
def sync_mailchimp():
    try:
        api_key = request.json.get("api_key")
        audience_id = request.json.get("audience_id")
        token = request.json.get("token")
        if not all([api_key, audience_id, token]):
            return jsonify({"error": "Missing api_key, audience_id, or token"}), 400

        status, contacts = realnex_get("Contacts", token)
        if status != 200:
            logging.error(f"Failed to fetch contacts: {contacts}")
            return jsonify({"error": "Failed to fetch contacts", "details": contacts}), 500

        synced = 0
        for c in contacts:
            payload = {
                "email_address": c['Email'],
                "status": "subscribed",
                "merge_fields": {
                    "FNAME": c.get("FirstName", ""),
                    "LNAME": c.get("LastName", "")
                }
            }
            member_id = c['Email'].lower()
            url = f"https://usX.api.mailchimp.com/3.0/lists/{audience_id}/members/{member_id}"
            headers = {"Authorization": f"apikey {api_key}"}
            try:
                response = requests.put(url, headers=headers, json=payload)
                if response.status_code in [200, 201]:
                    synced += 1
            except requests.RequestException as e:
                logging.warning(f"Failed to sync contact {c['Email']}: {str(e)}")

        logging.info(f"Synced {synced} contacts to Mailchimp")
        return jsonify({"synced": synced})
    except Exception as e:
        logging.error(f"Mailchimp sync failed: {str(e)}")
        return jsonify({"error": f"Sync failed: {str(e)}"}), 500

@app.route('/sync-constantcontact', methods=['POST'])
def sync_constantcontact():
    try:
        api_key = request.json.get("api_key")
        access_token = request.json.get("access_token")
        list_id = request.json.get("list_id")
        token = request.json.get("token")
        if not all([api_key, access_token, list_id, token]):
            return jsonify({"error": "Missing api_key, access_token, list_id, or token"}), 400

        status, contacts = realnex_get("Contacts", token)
        if status != 200:
            logging.error(f"Failed to fetch contacts: {contacts}")
            return jsonify({"error": "Failed to fetch contacts", "details": contacts}), 500

        synced = 0
        for c in contacts:
            contact = {
                "email_address": {"address": c['Email']},
                "first_name": c.get("FirstName", ""),
                "last_name": c.get("LastName", ""),
                "list_memberships": [list_id]
            }
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            try:
                response = requests.post("https://api.cc.email/v3/contacts/sign_up_form", headers=headers, json=contact)
                if response.status_code in [200, 201]:
                    synced += 1
            except requests.RequestException as e:
                logging.warning(f"Failed to sync contact {c['Email']}: {str(e)}")

        logging.info(f"Synced {synced} contacts to Constant Contact")
        return jsonify({"synced": synced})
    except Exception as e:
        logging.error(f"Constant Contact sync failed: {str(e)}")
        return jsonify({"error": f"Sync failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
