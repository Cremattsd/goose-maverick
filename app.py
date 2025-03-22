from flask import Flask, render_template, request, jsonify, session
import os
import openai
import pytesseract
import fitz  # PyMuPDF for PDF text extraction
import pandas as pd
from werkzeug.utils import secure_filename
from PIL import Image
import re

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecret")

openai.api_key = os.getenv("OPENAI_API_KEY")

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'csv', 'xlsx'}
UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_webp_to_png(webp_path):
    png_path = webp_path.rsplit('.', 1)[0] + ".png"
    with Image.open(webp_path).convert("RGB") as im:
        im.save(png_path, "PNG")
    return png_path

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    return "\n".join([page.get_text("text") for page in doc]).strip()

def extract_text_from_image(image_path):
    return pytesseract.image_to_string(image_path, config='--psm 6')

def extract_contact_from_image(image_path):
    text = extract_text_from_image(image_path)
    contact_info = {
        'name': next(iter(re.findall(r'([A-Z][a-z]+\s[A-Z][a-z]+)', text)), None),
        'email': next(iter(re.findall(r'[\w\.-]+@[\w\.-]+', text)), None),
        'phone': next(iter(re.findall(r'\+?[\d\s\-\(\)]{10,15}', text)), None)
    }
    return contact_info

def process_file(file_path, file_type):
    if file_type == 'webp':
        file_path = convert_webp_to_png(file_path)
        file_type = 'png'

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
    user_input = data.get("message", "").lower()
    role = data.get("role", "maverick")

    if "import data" in user_input or "upload file" in user_input:
        return jsonify({"response": "You can import data into your RealNex CRM by following these steps: 1. Access your RealNex CRM account. 2. Look for the import feature, which is typically located in the contacts or leads section. 3. Prepare your data in a CSV file format with the appropriate headers (e.g., name, email, phone number). 4. Follow the prompts to upload your CSV file and map the fields from your file to the corresponding fields in your RealNex CRM. 5. Review the imported data to ensure accuracy and completeness. If you encounter any issues during the import process, you can reach out to RealNex customer support for assistance. Would you like me to bring in Goose to handle the upload?"})

    if "yes" in user_input and "goose" in user_input or "bring in goose" in user_input:
        return jsonify({"switch_to": "goose", "response": "Alright, bringing in Goose to handle your import! Please upload your file and enter your token if you haven’t already."})

    if role == "goose" and ("token" in user_input or "where do i put my token" in user_input or "how do i add my token" in user_input):
        return jsonify({"response": "You can enter your RealNex API token in the token field just below the chat. Once entered, I’ll remember it for this session."})

    valid_keywords = ["realnex", "crm", "marketplace", "market edge", "marketedge", "transaction manager", "tour book", "lease analysis", "goose", "maverick"]
    if role == "maverick":
        if not any(kw in user_input for kw in valid_keywords):
            return jsonify({"response": "I'm here to assist with RealNex-related tools only — including CRM, MarketEdge, MarketPlace, Lease Analysis, Tour Book, and Transaction Manager."})
        prompt = (
            "You are Maverick, a RealNex AI assistant. Only answer questions related to the RealNex platform, including CRM, MarketEdge, MarketPlace, Lease Analysis, Tour Book, Transaction Manager, and file importing with Goose.\n"
            f"User: {user_input}"
        )
    else:
        prompt = (
            "You are Goose, an AI assistant that helps RealNex users upload and process files into the RealNex CRM and related tools.\n"
            f"User: {user_input}"
        )

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
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    token = request.form.get("token")

    if not token:
        token = session.get("token")
        if not token:
            return jsonify({"error": "Please provide your RealNex API token."}), 401
    else:
        session['token'] = token

    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file or file type."}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    file_type = filename.rsplit('.', 1)[1].lower()

    try:
        extracted = process_file(filepath, file_type)
    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

    return jsonify({
        "message": f"Goose processed your file: {filename}",
        "extracted_data": extracted[:1000]
    })

if __name__ == "__main__":
    app.run(debug=True)
