from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import openai
from werkzeug.utils import secure_filename
from ai.ocr_parser import extract_text_from_pdf, extract_text_from_image
from ai.llm import auto_match_fields

app = Flask(__name__)
app.secret_key = "your_secret_key"

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
openai.api_key = os.getenv("OPENAI_API_KEY")

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("home"))
    return render_template("dashboard.html", user=session["user"])

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"})

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        if filename.endswith(".pdf"):
            extracted_data = extract_text_from_pdf(filepath)
        else:
            extracted_data = extract_text_from_image(filepath)

        matched_data = auto_match_fields(extracted_data)

        return jsonify({"data": matched_data})

    return jsonify({"error": "Invalid file type"})

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
