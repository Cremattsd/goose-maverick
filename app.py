import os
import openai
from flask import Flask, request, jsonify, render_template
from ai.ocr_parser import parse_uploaded_file
from real_nex_sync_api_data_facade import RealNexSyncApiDataFacade  # ✅ Correct import

app = Flask(__name__)

# Use GPT-3.5 Turbo
openai.api_key = os.getenv("OPENAI_API_KEY")
GPT_MODEL = "gpt-3.5-turbo"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "")
        if not user_message:
            return jsonify({"error": "Message required"}), 400

        response = openai.ChatCompletion.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response.choices[0].message["content"]})

    except Exception as e:
        return jsonify({"error": f"Chatbot error: {str(e)}"}), 500

@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files['file']
        if not file:
            return jsonify({"error": "No file provided"}), 400

        filepath = f"./uploads/{file.filename}"
        file.save(filepath)

        extracted_data = parse_uploaded_file(filepath)
        user_token = request.form.get("user_token")  # ✅ User enters their API token

        # ✅ Initialize RealNex SDK client
        realnex_client = RealNexSyncApiDataFacade(api_token=user_token)
        result = realnex_client.upload_data(extracted_data)

        return jsonify({"status": "success", "uploaded": result})

    except Exception as e:
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
