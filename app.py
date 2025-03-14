import os
from flask import Flask, request, jsonify
import openai
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env (if running locally)

app = Flask(__name__)

# Load your OpenAI API key from Render secrets or local .env
openai.api_key = os.getenv("OPENAI_API_KEY")

if not openai.api_key:
    raise ValueError("Missing OPENAI_API_KEY. Ensure it's set in Render secrets.")

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
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
