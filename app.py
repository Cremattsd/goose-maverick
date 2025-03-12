from flask import Flask, request, jsonify, render_template
import openai
import os
from config import RealNexAPI

app = Flask(__name__)

# Set up OpenAI API Key
openai.api_key = os.getenv("OPENAI_API_KEY")
realnex_api = RealNexAPI()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip().lower()

    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400

    # Check if API token exists, if not ask the user to provide it
    if not realnex_api.api_token:
        return jsonify({"response": 
            "Welcome! I can assist you with RealNex. To unlock all features, "
            "please provide your RealNex API token. Don't have one? "
            "Click here to get it: https://realnex.com/api-tokens"
        })

    # Handle user input for common queries
    if "features" in user_message or "help" in user_message:
        return jsonify({"response":
            "I can do the following:\n"
            "✔️ Answer your commercial real estate questions\n"
            "✔️ Upload & parse property documents\n"
            "✔️ Scan business cards into contacts\n"
            "✔️ Auto-match data to CRM fields\n"
            "To start, just type what you need help with!"
        })

    # AI Response from OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_message}]
    )

    return jsonify({"response": response["choices"][0]["message"]["content"]})

@app.route("/set_token", methods=["POST"])
def set_token():
    data = request.json
    new_token = data.get("token", "").strip()

    if not new_token:
        return jsonify({"error": "Please provide a valid token"}), 400

    result = realnex_api.store_token(new_token)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
