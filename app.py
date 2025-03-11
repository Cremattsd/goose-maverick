import os
import requests
from flask import Flask, request, render_template, session, redirect, url_for, jsonify
from realnex_api import RealNexAPI
from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super_secret_key")

REALNEX_API_URL = "https://sync.realnex.com/api"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ai_client = OpenAI(api_key=OPENAI_API_KEY)

# Home route
@app.route("/")
def home():
    return render_template("index.html")

# Login route
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    auth_url = f"{REALNEX_API_URL}/auth/token"
    auth_payload = {"email": email, "password": password}

    try:
        response = requests.post(auth_url, json=auth_payload, timeout=10)

        if response.status_code == 200:
            user_data = response.json()
            session["user"] = {
                "id": user_data["id"],
                "token": user_data["token"]
            }
            return jsonify({"message": "Login successful", "user_id": user_data["id"]})
        else:
            return jsonify({"error": "Invalid credentials"}), 401

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request failed: {str(e)}"}), 500

# Dashboard
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("home"))
    return render_template("dashboard.html")

# File upload
@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user"]["id"]
    token = session["user"]["token"]
    uploaded_file = request.files.get("file")

    if uploaded_file:
        file_path = f"./uploads/{uploaded_file.filename}"
        uploaded_file.save(file_path)

        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": open(file_path, "rb")}
        data = {"user_id": user_id}

        response = requests.post(f"{REALNEX_API_URL}/upload", headers=headers, files=files, data=data)

        if response.status_code == 200:
            return jsonify({"message": "File uploaded successfully", "data": response.json()})
        else:
            return jsonify({"error": response.text}), response.status_code

    return jsonify({"error": "No file uploaded"}), 400

# AI Chatbot
@app.route("/chat", methods=["POST"])
def chat():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_question = data.get("question", "")

    token = session["user"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    crm_response = requests.get(f"{REALNEX_API_URL}/contacts", headers=headers)
    crm_data = crm_response.json() if crm_response.status_code == 200 else {}

    prompt = f"""
    User Question: {user_question}
    RealNex Data: {crm_data}
    AI, please provide a useful response based on this data.
    """

    ai_response = ai_client.Completion.create(
        model="gpt-4",
        prompt=prompt,
        max_tokens=150
    )

    return jsonify({"response": ai_response["choices"][0]["text"].strip()})

if __name__ == "__main__":
    app.run(debug=True)
