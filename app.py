from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import requests
import fitz  # PyMuPDF for PDF parsing
import pandas as pd
import pytesseract  # OCR for images
from PIL import Image
import os
import re
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

REALNEX_API_URL = "https://sync.realnex.com/api/client"

# ---------------- Home Route ----------------
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# ---------------- Login Route ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        api_key = request.form['api_key']
        headers = {"Authorization": f"Bearer {api_key}"}

        response = requests.get(REALNEX_API_URL, headers=headers)
        if response.status_code == 200:
            user_data = response.json()
            session['user'] = user_data.get("clientName", "Unknown User")
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid API Key')
    return render_template('login.html')

# ---------------- Dashboard Route ----------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    parsed_data = session.get('parsed_data', None)
    return render_template('dashboard.html', user=session['user'], data=parsed_data)

# ---------------- File Upload & Parsing ----------------
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

    parsed_data = parse_file(file_path)
    session['parsed_data'] = parsed_data

    return jsonify(parsed_data)

def parse_file(file_path):
    _, ext = os.path.splitext(file_path)
    if ext.lower() == ".pdf":
        return parse_pdf(file_path)
    elif ext.lower() in [".png", ".jpg", ".jpeg"]:
        return parse_image(file_path)
    elif ext.lower() in [".xls", ".xlsx"]:
        return parse_excel(file_path)
    return {"Error": "Unsupported file format"}

def parse_pdf(file_path):
    try:
        document = fitz.open(file_path)
        text = "\n".join(page.get_text() for page in document)
        document.close()
        return {"ExtractedText": text}
    except Exception as e:
        return {"Error": str(e)}

def parse_image(file_path):
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)  # OCR extraction
        return {"ExtractedText": text}
    except Exception as e:
        return {"Error": str(e)}

def parse_excel(file_path):
    try:
        df = pd.read_excel(file_path)
        return df.to_dict(orient='records')
    except Exception as e:
        return {"Error": str(e)}

# ---------------- Logout Route ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True)
