import os
import openai
import pytesseract
from PIL import Image
from flask import Flask, request, jsonify, render_template
from real_nex_sync_api_data_facade import RealNexSyncApiDataFacade  # RealNex SDK

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# 🚀 Home Page
@app.route("/")
def index():
    return render_template("index.html")

# 💬 Chat Route
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        user_message = data.get("message", "")

        if not user_message:
            return jsonify({"error": "Message required"}), 400

        # 🚀 Smart RealNex AI Assistant Context
        realnex_context = """
        You are a high-energy, expert AI assistant for RealNex! 
        You help commercial real estate professionals with:
        - RealNex CRM, MarketPlace, Lease Analysis, and Data Sync
        - Auto-importing data from business cards, PDFs, and Excel files
        - Generating professional emails instantly
        - Predictive analytics & market trends

        🔥 If users ask about importing data, explain they can drag & drop files.
        🔥 If they ask about emails, help them write professional responses.
        🔥 If unsure, provide fun, futuristic AI vibes while being helpful.
        """

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": realnex_context},
                {"role": "user", "content": user_message}
            ]
        )

        return jsonify({"response": response.choices[0].message["content"]})

    except Exception as e:
        return jsonify({"error": f"Chatbot error: {str(e)}"}), 500

# 📇 Business Card OCR Upload
@app.route("/upload_business_card", methods=["POST"])
def upload_business_card():
    try:
        file = request.files['file']
        if not file:
            return jsonify({"error": "No file provided"}), 400

        filepath = f"./uploads/{file.filename}"
        file.save(filepath)

        # 🚀 Extract Text Using OCR
        extracted_text = pytesseract.image_to_string(Image.open(filepath))

        contact_data = {"name": "", "company": "", "email": "", "phone": ""}
        for line in extracted_text.split("\n"):
            if "@" in line:
                contact_data["email"] = line.strip()
            elif any(char.isdigit() for char in line) and "-" in line:
                contact_data["phone"] = line.strip()
            elif len(line.split()) >= 2:
                if contact_data["name"] == "":
                    contact_data["name"] = line.strip()
                else:
                    contact_data["company"] = line.strip()

        user_token = request.form.get("user_token")

        # 🚀 Upload Contact to RealNex
        realnex_client = RealNexSyncApiDataFacade(api_token=user_token)
        result = realnex_client.upload_data(contact_data)

        return jsonify({"status": "success", "uploaded": result, "extracted_data": contact_data})

    except Exception as e:
        return jsonify({"error": f"Business card upload failed: {str(e)}"}), 500

# 📧 AI Email Generator
@app.route("/generate_email", methods=["POST"])
def generate_email():
    try:
        data = request.json
        email_purpose = data.get("purpose", "")

        if not email_purpose:
            return jsonify({"error": "Email purpose required"}), 400

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI helping users write professional commercial real estate emails."},
                {"role": "user", "content": f"Write an email for: {email_purpose}"}
            ]
        )

        return jsonify({"email": response.choices[0].message["content"]})

    except Exception as e:
        return jsonify({"error": f"Email generation failed: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
