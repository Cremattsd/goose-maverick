import os
import openai
from flask import Flask, request, jsonify, render_template
from ai.ocr_parser import parse_uploaded_file  # Ensure this is correct
from realnex_api import upload_data_to_realnex  # Ensure this is correct

# Initialize Flask App
app = Flask(__name__)

# Load API Key from Environment Variables
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("❌ Missing OPENAI_API_KEY. Set it in your environment variables!")

@app.route("/")
def index():
    return render_template("index.html")

# ✅ Chat Route (GPT-3.5 or GPT-4)
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"error": "Message required"}), 400

        # ✅ Use GPT-3.5-Turbo (or GPT-4 if available)
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Change to "gpt-4" if available
            messages=[{"role": "user", "content": user_message}]
        )

        return jsonify({"response": response["choices"][0]["message"]["content"]})

    except Exception as e:
        return jsonify({"error": str(e)}), 500  # Return full error message

# ✅ File Upload Route
@app.route("/upload", methods=["POST"])
def upload():
    try:
        # Get File & API Token
        file = request.files.get("file")
        user_token = request.form.get("api_token")

        if not file:
            return jsonify({"error": "No file provided"}), 400
        if not user_token:
            return jsonify({"error": "API Token required"}), 400

        # Save File
        filepath = f"./uploads/{file.filename}"
        file.save(filepath)

        # Extract Data
        extracted_data = parse_uploaded_file(filepath)

        # Upload Data to RealNex
        result = upload_data_to_realnex(extracted_data, user_token)

        return jsonify({"status": "success", "uploaded": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
