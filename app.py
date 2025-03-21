from flask import Flask, render_template, request, jsonify
import os
import openai
import pytesseract
import fitz  # PyMuPDF for PDF text extraction
import pandas as pd
from werkzeug.utils import secure_filename
import re

app = Flask(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'csv', 'xlsx'}
UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

USER_TOKEN = None  # Stores user's API token after first Goose upload

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    return "\n".join([page.get_text("text") for page in doc]).strip()

def extract_text_from_image(image_path):
    return pytesseract.image_to_string(image_path)

def extract_contact_from_image(image_path):
    text = extract_text_from_image(image_path)
    contact_info = {
        'name': next(iter(re.findall(r'([A-Z][a-z]+\s[A-Z][a-z]+)', text)), None),
        'email': next(iter(re.findall(r'[\w\.-]+@[\w\.-]+', text)), None),
        'phone': next(iter(re.findall(r'\+?[\d\s\-\(\)]{10,15}', text)), None)
    }
    return contact_info

def process_file(file_path, file_type):
    if file_type in {'png', 'jpg', 'jpeg'}:
        contact = extract_contact_from_image(file_path)
        if any(contact.values()):
            return f"Business Card Found:\nName: {contact['name']}\nEmail: {contact['email']}\nPhone: {contact['phone']}"
        else:
            return extract_text_from_image(file_path)
    elif file_type == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_type == 'csv':
        df = pd.read_csv(file_path)
        return df.to_string()
    elif file_type == 'xlsx':
        df = pd.read_excel(file_path)
        return df.to_string()
    else:
        return "Unsupported file type."

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_input = data.get("message", "")
    role = data.get("role", "maverick")

    if "import data" in user_input.lower() or "upload file" in user_input.lower():
        return jsonify({"response": "You can import data into your RealNex CRM by following these steps: 1. Access your RealNex CRM account. 2. Look for the import feature, which is typically located in the contacts or leads section. 3. Prepare your data in a CSV file format with the appropriate headers (e.g., name, email, phone number). 4. Follow the prompts to upload your CSV file and map the fields from your file to the corresponding fields in your RealNex CRM. 5. Review the imported data to ensure accuracy and completeness. If you encounter any issues during the import process, you can reach out to RealNex customer support for assistance. Would you like me to bring in Goose to handle the upload?"})

    if role == "maverick":
        prompt = f"You are Maverick, a RealNex AI assistant. Answer user questions about commercial real estate tools and workflows.\nUser: {user_input}"
    else:
        prompt = f"You are Goose, an AI assistant helping users upload and process files into RealNex.\nUser: {user_input}"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": prompt}]
        )
        return jsonify({"response": response.choices[0].message["content"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload_file():
    global USER_TOKEN

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    token = request.form.get("token")

    if not token:
        if USER_TOKEN:
            token = USER_TOKEN
        else:
            return jsonify({"error": "Please provide your RealNex API token."}), 401

    if not USER_TOKEN:
        USER_TOKEN = token  # store it for this session

    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file or file type."}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    file_type = filename.rsplit('.', 1)[1].lower()
    extracted = process_file(filepath, file_type)

    return jsonify({
        "message": f"Goose processed your file: {filename}",
        "extracted_data": extracted[:1000]  # preview
    })

if __name__ == "__main__":
    app.run(debug=True)
