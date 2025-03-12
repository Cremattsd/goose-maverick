from flask import Flask, render_template, request, jsonify, session
import requests
import os
import openai
import json
from werkzeug.utils import secure_filename
from realnex_api import RealNexAPI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

openai.api_key = os.getenv("OPENAI_API_KEY")

# Home Page
@app.route("/")
def home():
    return render_template("index.html")

# Handle AI Chat Requests
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Handle API Key Submission
@app.route("/submit_token", methods=["POST"])
def submit_token():
    token = request.form.get("token")
    if token:
        session["realnex_token"] = token
        return jsonify({"message": "Token saved successfully!"})
    return jsonify({"error": "No token provided"}), 400

# Handle File Uploads
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    return jsonify({"message": "File uploaded successfully", "file_path": file_path})

if __name__ == "__main__":
    app.run(debug=True)
