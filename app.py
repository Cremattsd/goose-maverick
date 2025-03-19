import os
import openai
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from real_nex_sync_api_data_facade import RealNexClient  # Import RealNex SDK
from ai.ocr_parser import parse_uploaded_file  # Import OCR parser

# Initialize Flask App
app = Flask(__name__)

# Set OpenAI API Key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configure upload folder
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Render Homepage
@app.route("/")
def index():
    return render_template("index.html")

# Chatbot API
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "Message required"}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Using GPT-3.5 Turbo
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# File Upload & Data Extraction API
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    try:
        extracted_data = parse_uploaded_file(filepath)  # Process file
        user_token = request.form.get("user_token")  # User provides their RealNex token
        
        if not user_token:
            return jsonify({"error": "Missing RealNex token"}), 400

        # Initialize RealNex API client
        realnex_client = RealNexClient(api_key=user_token)
        upload_result = realnex_client.upload_data(extracted_data)

        return jsonify({"status": "success", "uploaded": upload_result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Send Daily Events via Email API
@app.route("/send-daily-events", methods=["POST"])
def send_daily_events():
    user_email = request.json.get("email", "")
    user_token = request.json.get("user_token", "")

    if not user_email or not user_token:
        return jsonify({"error": "Email and RealNex token are required"}), 400

    try:
        realnex_client = RealNexClient(api_key=user_token)
        events = realnex_client.get_daily_events()

        if not events:
            return jsonify({"message": "No events found for today"}), 200

        email_body = "\n".join([f"{event['title']} - {event['date']}" for event in events])
        
        # Mock sending email
        print(f"Sending email to {user_email}:\n{email_body}")

        return jsonify({"status": "success", "message": f"Events sent to {user_email}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Run the Flask App
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
