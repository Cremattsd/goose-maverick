import os
import openai
from flask import Flask, request, jsonify, render_template
from ai.ocr_parser import parse_uploaded_file
from realnex_api import upload_data_to_realnex

app = Flask(__name__)

# Ensure OpenAI API Key is loaded
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Missing OpenAI API Key. Set it in Render's environment variables.")

openai.api_key = OPENAI_API_KEY

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
            model="gpt-4",
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    company_id = request.form.get("company_id")

    if not file:
        return jsonify({"error": "No file provided"}), 400

    filepath = f"./uploads/{file.filename}"
    file.save(filepath)

    extracted_data = parse_uploaded_file(filepath)

    if company_id:
        result = upload_data_to_realnex(extracted_data, company_id)
        return jsonify({"status": "success", "uploaded": result})

    return jsonify({"status": "success", "extracted_data": extracted_data})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
