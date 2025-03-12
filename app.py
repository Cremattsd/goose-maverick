from flask import Flask, request, jsonify, render_template, session
import os
from config import RealNexAPI

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

# Initialize RealNexAPI
realnex_api = RealNexAPI()

@app.route("/")
def home():
    """Render the homepage with API status"""
    api_enabled = realnex_api.is_api_enabled() or "REALNEX_API_TOKEN" in session
    return render_template("index.html", api_enabled=api_enabled)

@app.route("/set_api_key", methods=["POST"])
def set_api_key():
    """Save API key when user enters it"""
    data = request.json
    api_key = data.get("api_key")
    
    if api_key:
        session["REALNEX_API_TOKEN"] = api_key  # Store token in session
        os.environ["REALNEX_API_TOKEN"] = api_key  # Set for session
        return jsonify({"message": "✅ API key saved successfully! Advanced features enabled."})
    else:
        return jsonify({"error": "⚠️ No API key provided."}), 400

@app.route("/chat", methods=["POST"])
def chat():
    """Handle AI chatbot messages"""
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400

    # Example AI Response (Replace with OpenAI API call)
    response = f"AI Response: {user_message} (This is a placeholder response.)"

    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(debug=True)
