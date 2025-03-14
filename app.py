import os
from openai import OpenAI  # ✅ Correct import
from flask import Flask, request, jsonify

# Initialize Flask app
app = Flask(__name__)

# Ensure the API key is read correctly
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY. Make sure it's set in Render secrets.")

# ✅ Correct OpenAI client initialization
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route("/")
def home():
    return "API is running!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = client.chat.completions.create(  # ✅ Correct method call
            model="gpt-4",
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
