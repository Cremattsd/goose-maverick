import os
import logging
from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
import requests
from realnex_api import RealNexAPI
from openai import OpenAI  # Ensure OpenAI API Key is configured in .env
import pytesseract
from PIL import Image
import pandas as pd

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'xls', 'xlsx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO)

realnex = RealNexAPI(api_key=os.getenv("REALNEX_API_KEY"))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return "Unauthorized", 401
    return render_template('dashboard.html', user=session['user'])

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        if filename.endswith(('.png', '.jpg', '.jpeg')):
            extracted_text = extract_text_from_image(file_path)
            return jsonify({"message": "File uploaded successfully", "extracted_text": extracted_text})
        
        elif filename.endswith(('.xls', '.xlsx')):
            extracted_data = extract_data_from_excel(file_path)
            return jsonify({"message": "File uploaded successfully", "extracted_data": extracted_data})
        
        return jsonify({"message": "File uploaded successfully"}), 200
    else:
        return jsonify({"error": "Invalid file format"}), 400

def extract_text_from_image(image_path):
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)
    return text.strip()

def extract_data_from_excel(file_path):
    df = pd.read_excel(file_path)
    return df.to_dict(orient='records')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get("message", "")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    ai_response = chat_with_openai(user_message)
    return jsonify({"response": ai_response})

def chat_with_openai(message):
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        return "OpenAI API Key missing"
    
    response = OpenAI(api_key=openai_api_key).chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": message}]
    )
    
    return response.choices[0].message['content']

if __name__ == '__main__':
    app.run(debug=True)
