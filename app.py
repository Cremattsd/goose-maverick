import os
from flask import Flask, render_template, request, jsonify, session
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")  # Change to a real secret key

# OpenAI API Key from environment variable
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Store user token in session
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        session["realnex_token"] = request.form.get("realnex_token")
    return render_template("index.html", token=session.get("realnex_token"))

# AI Chat Route
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": message}]
        )

        return jsonify({"response": response.choices[0].message.content})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
