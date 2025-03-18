import os
import openai
from flask import Flask, request, jsonify, render_template
from ai.ocr_parser import parse_uploaded_file
from real_nex_sync_api_data_facade import RealNexSyncApiDataFacade

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
    file = request.files.get('file')
    token = request.form.get("token")

    if not file or not token:
        return jsonify({"error": "File and token required"}), 400

    filepath = f"./uploads/{file.filename}"
    file.save(filepath)

    extracted_data = parse_uploaded_file(filepath)

    # Initialize RealNex SDK
    realnex_client = RealNexSyncApiDataFacade(environment="production", token=token)

    # Upload extracted data
    upload_response = realnex_client.upload_data(extracted_data)

    return jsonify({"status": "success", "uploaded": upload_response})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
