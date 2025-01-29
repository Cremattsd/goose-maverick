from flask import Flask, render_template, request, redirect, url_for, session
import requests
import fitz  # PyMuPDF for PDF parsing
import pandas as pd
import os
import re
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

REALNEX_API_URL = "https://sync.realnex.com/api/client"

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
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid API Key')
    return render_template('login.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            parsed_data = parse_file(file_path)
            return render_template('dashboard.html', user=session['user'], data=parsed_data)

    return render_template('dashboard.html', user=session['user'])

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

def parse_file(file_path):
    _, ext = os.path.splitext(file_path)
    if ext.lower() == ".pdf":
        return parse_pdf(file_path)
    elif ext.lower() in [".xls", ".xlsx"]:
        return parse_excel(file_path)
    elif ext.lower() in [".png", ".jpg", ".jpeg"]:
        return parse_image(file_path)
    else:
        return {"Error": "Unsupported file format"}

def parse_pdf(file_path):
    try:
        document = fitz.open(file_path)
        text = ""
        for page in document:
            text += page.get_text()
        document.close()
        
        # Extract key information using regex
        extracted_data = {
            "Property Address": re.search(r"\d{1,5}\s[\w\s]+,\s?[\w\s]+", text).group(0) if re.search(r"\d{1,5}\s[\w\s]+,\s?[\w\s]+", text) else "N/A",
            "City State": re.search(r"[A-Za-z]+,\s[A-Z]{2}\s\d{5}", text).group(0) if re.search(r"[A-Za-z]+,\s[A-Z]{2}\s\d{5}", text) else "N/A",
            "Number of Units": re.search(r"Number of Units\s+(\d+)", text).group(1) if re.search(r"Number of Units\s+(\d+)", text) else "N/A",
            "Rentable SqFt": re.search(r"Rentable SqFt\s+(\d+,?\d*)", text).group(1) if re.search(r"Rentable SqFt\s+(\d+,?\d*)", text) else "N/A",
            "Contact Name": re.search(r"Managing Director\\n([A-Za-z\s]+)", text).group(1) if re.search(r"Managing Director\\n([A-Za-z\s]+)", text) else "N/A",
            "Email": re.search(r"[\w.]+@[\w.]+", text).group(0) if re.search(r"[\w.]+@[\w.]+", text) else "N/A",
            "Cap Rate": re.search(r"Cap Rate\s+(\d+.\d+%)", text).group(1) if re.search(r"Cap Rate\s+(\d+.\d+%)", text) else "N/A",
            "Pro Forma Cap Rate": re.search(r"Pro Forma Cap Rate\s+(\d+.\d+%)", text).group(1) if re.search(r"Pro Forma Cap Rate\s+(\d+.\d+%)", text) else "N/A",
            "Net Operating Income": re.search(r"Net Operating Income\s+\$(\d+,?\d*)", text).group(1) if re.search(r"Net Operating Income\s+\$(\d+,?\d*)", text) else "N/A"
        }
        
        return extracted_data
    except Exception as e:
        return {"Error": str(e)}

def parse_excel(file_path):
    try:
        data = pd.read_excel(file_path)
        return data.to_dict(orient="records")
    except Exception as e:
        return {"Error": str(e)}

def parse_image(file_path):
    try:
        return {"ExtractedText": "Image processing functionality to be added."}
    except Exception as e:
        return {"Error": str(e)}

if __name__ == "__main__":
    app.run(debug=True)
