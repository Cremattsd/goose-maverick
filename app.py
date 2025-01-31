import os
import json
import fitz  # PyMuPDF for PDF parsing
import pytesseract
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
import openai  # AI for auto-matching fields

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey")

# OpenAI API Key
openai.api_key = os.environ.get("OPENAI_API_KEY")

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "xlsx"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text


def extract_text_from_image(image_path):
    """Extract text from an image using Tesseract OCR."""
    image = Image.open(image_path)
    return pytesseract.image_to_string(image)


def auto_match_fields(text):
    """Use OpenAI to intelligently match extracted text to CRM fields."""
    prompt = f"""
    Given the following extracted text, identify and map the fields to CRM-relevant fields.

    Extracted Text:
    {text}

    Return the data in JSON format like this:
    {{
        "property_name": "Example Property",
        "address": "123 Main St, City, State",
        "price": "$1,500,000",
        "cap_rate": "5.2%",
        "number_of_units": "20",
        "agent_name": "John Doe",
        "agent_phone": "555-123-4567",
        "agent_email": "johndoe@email.com"
    }}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        return json.loads(response["choices"][0]["message"]["content"])
    except Exception as e:
        print("Error parsing AI response:", e)
        return {}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        api_key = request.form.get("api_key")
        if api_key:
            session["user"] = api_key  # Mock login with API key
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid API Key")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    # Placeholder for parsed data
    parsed_data = session.get("parsed_data", {})

    if not isinstance(parsed_data, dict):
        parsed_data = {}

    return render_template("dashboard.html", user=session["user"], data=parsed_data)


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
            extracted_text = extract_text_from_pdf(filepath)
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            extracted_text = extract_text_from_image(filepath)
        else:
            extracted_text = "Unsupported file type"

        mapped_data = auto_match_fields(extracted_text)
        session["parsed_data"] = mapped_data  # Store in session

        return jsonify(mapped_data)

    return jsonify({"error": "Invalid file type"})


@app.route("/send_to_crm", methods=["POST"])
def send_to_crm():
    # Simulated CRM endpoint (this would actually send data to RealNex CRM)
    crm_data = request.json
    print("Sending to CRM:", crm_data)
    return jsonify({"success": True, "message": "Data successfully sent to CRM"})


if __name__ == "__main__":
    app.run(debug=True)
