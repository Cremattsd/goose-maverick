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

# MAVERICK - The Knowledge Bot 💡
@app.route("/maverick", methods=["POST"])
def maverick():
    try:
        data = request.json
        user_message = data.get("message", "")

        if not user_message:
            return jsonify({"error": "Message required"}), 400

        maverick_context = """
        Your name is MAVERICK. You are a high-energy, badass AI mentor that guides users through the RealNex ecosystem.
        You know EVERYTHING about RealNex, including:
        - CRM, MarketPlace, Lease Analysis, and Data Sync
        - How to use each feature like a pro
        - Best practices, FAQs, and workflow optimization

        🎯 If users ask about importing data, hand it off to GOOSE.
        🎯 If they need RealNex guidance, teach them step-by-step.
        🎯 Always respond with a confident, action-packed, and engaging personality.
        """

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": maverick_context},
                {"role": "user", "content": user_message}
            ]
        )

        return jsonify({"response": response.choices[0].message["content"]})

    except Exception as e:
        return jsonify({"error": f"Maverick error: {str(e)}"}), 500

# GOOSE - The Data Import Bot 📊
@app.route("/goose", methods=["POST"])
def goose():
    try:
        file = request.files['file']
        user_token = request.form.get("user_token")

        if not file:
            return jsonify({"error": "No file provided"}), 400

        filepath = f"./uploads/{file.filename}"
        file.save(filepath)

        # 🚀 Extract Text Using OCR for Business Cards
        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
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

            # 🚀 Upload Contact to RealNex
            realnex_client = RealNexSyncApiDataFacade(api_token=user_token)
            result = realnex_client.upload_data(contact_data)
            return jsonify({"status": "success", "uploaded": result, "extracted_data": contact_data})

        # 🚀 Uploading PDFs & Excel Sheets
        realnex_client = RealNexSyncApiDataFacade(api_token=user_token)
        result = realnex_client.upload_file(filepath)

        return jsonify({"status": "success", "uploaded": result})

    except Exception as e:
        return jsonify({"error": f"Goose error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
