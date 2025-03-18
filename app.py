import os
import openai
from flask import Flask, request, jsonify, render_template
from ai.ocr_parser import parse_uploaded_file
from real_nex_sync_api_data_facade import RealNexClient

# Initialize Flask
app = Flask(__name__)

# Initialize OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize RealNex Client with your SDK
realnex_client = RealNexClient(api_key=os.getenv("REALNEX_API_KEY"))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message")

    if not user_message:
        return jsonify({"error": "Message required"}), 400

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_message}]
    )

    reply = response.choices[0].message.content
    return jsonify({"response": reply})

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file provided"}), 400

    company_id = request.form.get("company_id")
    if not company_id:
        return jsonify({"error": "Company ID required"}), 400

    # Save file temporarily
    filepath = f"./uploads/{file.filename}"
    file.save(filepath)

    # Parse file and extract data
    extracted_data = parse_uploaded_file(filepath)

    # Upload data to RealNex
    upload_response = realnex_client.upload_data(company_id, extracted_data)

    # Check upload success
    if upload_response.get("success"):
        return jsonify({"status": "success", "details": upload_response})
    else:
        return jsonify({"status": "error", "details": upload_response}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
