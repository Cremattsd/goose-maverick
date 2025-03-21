from flask import Flask, render_template, request, jsonify
import os
import openai
import pytesseract
import fitz  # PyMuPDF for PDF text extraction
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Allowed file types
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'csv', 'xlsx', 'vcard'}

# Upload folder
UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Check file type
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Extract text from PDF
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text.strip()

# Extract text from image
def extract_text_from_image(image_path):
    return pytesseract.image_to_string(image_path)

# Process uploaded file
def process_file(file_path, file_type):
    if file_type in {'png', 'jpg', 'jpeg'}:
        extracted_text = extract_text_from_image(file_path)
    elif file_type == 'pdf':
        extracted_text = extract_text_from_pdf(file_path)
    elif file_type == 'csv':
        df = pd.read_csv(file_path)
        extracted_text = df.to_string()
    elif file_type == 'xlsx':
        df = pd.read_excel(file_path)
        extracted_text = df.to_string()
    elif file_type == 'vcard':
        # Handle business card scanning, convert to vCard format
        extracted_text = "Business card data: [sample extracted data]"
    else:
        extracted_text = "Unsupported file type"
    
    return extracted_text

# Handle token storage for Goose
USER_TOKEN = None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")
    role = request.json.get("role")

    if role == "maverick":
        prompt = f"You are Maverick, a RealNex AI assistant. Answer all RealNex-related questions professionally. User: {user_input}"
    elif role == "goose":
        prompt = f"You are Goose, a data import AI bot. Assist with importing and managing files. User: {user_input}"
    else:
        prompt = f"User: {user_input}"

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": prompt}]
    )

    return jsonify({"response": response["choices"][0]["message"]["content"]})

@app.route("/upload", methods=["POST"])
def upload_file():
    global USER_TOKEN

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files['file']
    user_token = request.form.get("token")

    # If no token is provided, prompt for it
    if not user_token:
        if USER_TOKEN:
            user_token = USER_TOKEN
        else:
            return jsonify({"error": "Please insert your RealNex API token."}), 401

    # Store the token if not already stored
    if USER_TOKEN is None and user_token:
        USER_TOKEN = user_token

    if file.filename == '':
        return jsonify({"error": "No selected file."}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        file_type = filename.rsplit('.', 1)[1].lower()
        extracted_data = process_file(file_path, file_type)

        return jsonify({
            "message": f"Goose uploaded and processed your file: {filename}",
            "extracted_data": extracted_data[:500]  # Show preview of data
        })

    return jsonify({"error": "Invalid file type."}), 400

if __name__ == "__main__":
    app.run(debug=True)