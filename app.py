from flask import Flask, render_template, request, jsonify, session
import openai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set OpenAI API Key Correctly
openai.api_key = OPENAI_API_KEY  # ✅ This is the correct way

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/set_token', methods=['POST'])
def set_token():
    token = request.form.get("token")
    if token:
        session['realnex_token'] = token
        return jsonify({"success": "Token saved!"})
    return jsonify({"error": "No token provided."})

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get("message", "")
    if not user_message:
        return jsonify({"error": "Message is empty!"})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an AI assistant for commercial real estate professionals."},
                {"role": "user", "content": user_message}
            ]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    except Exception as e:
        return jsonify({"error": f"OpenAI API error: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True)
