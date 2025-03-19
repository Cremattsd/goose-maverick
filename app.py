import os
import openai
from flask import Flask, request, jsonify

app = Flask(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Message required"}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",  # Change if needed
            messages=[{"role": "user", "content": user_message}]
        )
        return jsonify({"response": response["choices"][0]["message"]["content"]})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
