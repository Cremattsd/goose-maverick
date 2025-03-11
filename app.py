from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import requests
import logging
from werkzeug.utils import secure_filename

# Configure Logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls', 'png', 'jpg', 'jpeg'}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Ensure uploads folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Helper function: Check file type
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 🏠 Home Page
@app.route("/")
def home():
    return render_template("index.html")

# 📂 File Upload
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        return jsonify({"message": "File uploaded successfully", "filename": filename}), 200
    
    return jsonify({"error": "Invalid file type"}), 400

# 🖥️ Dashboard Route
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# 💬 AI Chatbot
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_input = data.get("message", "")

    if not user_input:
        return jsonify({"error": "Empty message"}), 400

    # AI Response
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": user_input}]
    }
    
    response = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
    
    if response.status_code == 200:
        ai_response = response.json()["choices"][0]["message"]["content"]
        return jsonify({"response": ai_response})
    
    return jsonify({"error": "Failed to get AI response"}), 500

if __name__ == "__main__":
    app.run(debug=True)
