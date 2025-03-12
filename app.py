from flask import Flask, request, jsonify, render_template, session
import openai
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Secure session storage

# Set OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/")
def index():
    return render_template("index.html", api_enabled="realnex_api_key" in session)

# ✅ Save RealNex API Key from User
@app.route("/set_api_key", methods=["POST"])
def set_api_key():
    data = request.json
    session["realnex_api_key"] = data.get("api_key")
    return jsonify({"message": "API Key saved successfully!"})

# ✅ AI Chatbot Route
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty!"})

    # Check if user added their RealNex API Key
    realnex_api_key = session.get("realnex_api_key")
    if realnex_api_key:
        realnex_url = "https://sync.realnex.com/api/chat"
        headers = {"Authorization": f"Bearer {realnex_api_key}"}
        response = requests.post(realnex_url, headers=headers, json={"query": user_message})

        if response.status_code == 200:
            return jsonify({"response": response.json().get("data", "No response from RealNex API.")})
    
    # Default to OpenAI if RealNex API is not enabled
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "You are a real estate AI assistant."},
                      {"role": "user", "content": user_message}]
        )
        ai_response = response["choices"][0]["message"]["content"]
    except Exception as e:
        ai_response = f"Error: {str(e)}"

    return jsonify({"response": ai_response})

if __name__ == "__main__":
    app.run(debug=True)
