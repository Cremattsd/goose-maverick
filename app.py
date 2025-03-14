import os
import openai
from flask import Flask, request, jsonify, render_template, redirect
from ai.ocr_parser import parse_uploaded_file
from realnex_api import upload_data_to_realnex

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    if not user_message:
        return jsonify({"error": "Message required"}), 400
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_message}]
    )
    return jsonify({"response": response.choices[0].message.content})

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files['file']
    if not file:
        return jsonify({"error": "No file provided"}), 400

    filepath = f"./uploads/{file.filename}"
    file.save(filepath)

    extracted_data = parse_uploaded_file(filepath)
    company_id = request.form.get("company_id")  # Provided by user through interface

    # Verify data and upload
    result = upload_data_to_realnex(extracted_data, company_id)
    
    return jsonify({"status": "success", "uploaded": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
