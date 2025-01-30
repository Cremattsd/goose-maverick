from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import requests
import fitz  # PyMuPDF for PDF parsing
import json
import os
import openai  # AI for auto-matching fields
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

REALNEX_API_URL = "https://sync.realnex.com/api/client"

# 🔥 Fetch CRM Fields from RealNex API & Store Locally
@app.route('/crm_fields', methods=['GET'])
def get_crm_fields():
    """Fetch all available CRM fields from RealNex API and store for AI."""
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    headers = {"Authorization": f"Bearer {session.get('api_key')}"}
    response = requests.get("https://sync.realnex.com/api/schema", headers=headers)  # Adjust API endpoint

    if response.status_code == 200:
        crm_fields = response.json().get("fields", [])
        
        # 🔥 Store fields for AI auto-matching
        with open("crm_fields.json", "w") as file:
            json.dump({"fields": crm_fields}, file, indent=4)
        
        return jsonify(crm_fields)  # Send to frontend
    else:
        return jsonify({"error": "Failed to fetch CRM fields"}), 500

# 🔥 File Upload & Parsing
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    parsed_data = parse_pdf(file_path)
    session['parsed_data'] = parsed_data  # Store for UI

    return jsonify(parsed_data)

# 🔥 PDF Parsing & AI Auto-Matching
def parse_pdf(file_path):
    """Parses a PDF and extracts multiple property listings."""
    try:
        document = fitz.open(file_path)
        raw_text = "\n".join(page.get_text("text") for page in document)
        document.close()
        
        # AI-based field extraction
        structured_data = extract_properties_with_ai(raw_text)
        
        return structured_data
    except Exception as e:
        return {"Error": str(e)}

def extract_properties_with_ai(raw_text):
    """Uses AI to extract structured property data & auto-match CRM fields."""
    
    # Load CRM fields
    with open("crm_fields.json", "r") as file:
        crm_fields = json.load(file)["fields"]
    
    prompt = f"""
    Extract all real estate properties from the following text.
    Each property should be structured using these CRM fields:

    {", ".join(crm_fields)}

    If a field is missing from the text, return "N/A".
    Also, auto-match extracted values to their correct RealNex CRM fields.

    Text:
    {raw_text}

    Return JSON:
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": "You are a real estate CRM data extraction expert."},
                  {"role": "user", "content": prompt}]
    )

    structured_data = response["choices"][0]["message"]["content"]
    return json.loads(structured_data)

# 🔥 Send Data to CRM
@app.route('/send_to_crm', methods=['POST'])
def send_to_crm():
    """Send multiple properties to RealNex CRM."""
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401

    properties = request.json.get("properties", [])
    headers = {"Authorization": f"Bearer {session.get('api_key')}", "Content-Type": "application/json"}
    
    success_count = 0
    for property_data in properties:
        mapped_data = {property_data["crm_mapping"][key]: value for key, value in property_data.items() if key != "crm_mapping"}
        response = requests.post("https://sync.realnex.com/api/properties", headers=headers, json=mapped_data)
        
        if response.status_code == 201:
            success_count += 1

    return jsonify({"success": True, "message": f"{success_count} properties sent to CRM."})

# 🔥 Authentication Routes
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        api_key = request.form['api_key']
        headers = {"Authorization": f"Bearer {api_key}"}

        response = requests.get(REALNEX_API_URL, headers=headers)
        if response.status_code == 200:
            user_data = response.json()
            session['user'] = user_data.get("clientName", "Unknown User")
            session['api_key'] = api_key  # Store API key for authentication
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid API Key')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    parsed_data = session.get('parsed_data', None)
    return render_template('dashboard.html', user=session['user'], data=parsed_data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True)
