import os
import openai
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Ensure API key is set
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY. Make sure it's set in Render secrets.")

openai.api_key = OPENAI_API_KEY  # ✅ Correct way to set API key

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Message required"}), 400
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    
    except openai.error.AuthenticationError:
        return jsonify({"error": "Invalid OpenAI API Key. Check your key."}), 500
    
    except openai.error.RateLimitError:
        return jsonify({"error": "OpenAI API rate limit exceeded. Try again later."}), 500
    
    except Exception as e:
        print(f"Chatbot Error: {e}")  # Logs the exact error to your Render logs
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
