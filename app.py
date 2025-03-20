import os
import openai
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import base64
from ai.ocr_parser import parse_uploaded_file
from realnex_api import upload_data_to_realnex

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Allowed file types
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Message required"}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Using GPT-3.5 Turbo
            messages=[
                {"role": "system", "content": "You are Maverick, a powerful AI assistant for RealNex. You answer RealNex-related questions, assist with commercial real estate tasks, and help process business cards and files."},
                {"role": "user", "content": user_message}
            ]
        )
        bot_response = response["choices"][0]["message"]["content"]
    except Exception as e:
        bot_response = "Maverick is having trouble retrieving information right now. Try again later."

    return jsonify({"response": bot_response})

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join("uploads", filename)
        file.save(filepath)

        # Process file using OCR & upload data
        extracted_data = parse_uploaded_file(filepath)
        api_token = request.form.get("api_token")

        if not api_token:
            return jsonify({"error": "API token required for upload"}), 400

        result = upload_data_to_realnex(extracted_data, api_token)
        return jsonify({"status": "success", "uploaded": result})
    
    return jsonify({"error": "Invalid file type"}), 400

@app.route("/upload-business-card", methods=["POST"])
def upload_business_card():
    data = request.json
    image_data = data.get("image_data", "")

    if not image_data:
        return jsonify({"error": "No image data provided"}), 400

    image_bytes = base64.b64decode(image_data)
    filepath = "uploads/business_card.png"
    
    with open(filepath, "wb") as file:
        file.write(image_bytes)

    extracted_data = parse_uploaded_file(filepath)
    api_token = data.get("api_token")

    if not api_token:
        return jsonify({"error": "API token required for processing"}), 400

    result = upload_data_to_realnex(extracted_data, api_token)
    return jsonify({"status": "success", "uploaded": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)