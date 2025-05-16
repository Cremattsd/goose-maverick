// === app.py: Now supports dashboard phrase detection + file upload + Goose OCR with CRM sync + graph data + weekly summary + auto-clean ===

from flask import Flask, request, jsonify, send_file
from datetime import datetime, timedelta
import os, json
from PIL import Image
import pytesseract

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
ERROR_LOG = 'errors.log'
CRM_DATA_FILE = 'scanned_data_points.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DASHBOARD_PHRASES = [
    "show me the dashboard", "open the dashboard", "dashboard please",
    "launch dashboard", "give me an update", "open goose dashboard",
    "pull my metrics", "sync update", "how are my stats", "check my data"
]

@app.route('/dashboard/stats')
def dashboard_stats():
    try:
        files = os.listdir(UPLOAD_FOLDER)
        latest = max([os.path.getmtime(os.path.join(UPLOAD_FOLDER, f)) for f in files], default=0)
        with open(CRM_DATA_FILE, 'r') as f:
            records = json.load(f)
        return jsonify({
            "filesUploaded": len(files),
            "lastUploadTime": datetime.fromtimestamp(latest).isoformat() if latest else "N/A",
            "scannedPoints": len(records)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/errors')
def dashboard_errors():
    try:
        if not os.path.exists(ERROR_LOG): return jsonify({"errors": []})
        with open(ERROR_LOG, 'r') as f:
            return jsonify({"errors": f.readlines()[-10:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/data')
def dashboard_data():
    try:
        if not os.path.exists(CRM_DATA_FILE):
            return jsonify([])
        with open(CRM_DATA_FILE, 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/weekly-summary')
def dashboard_weekly_summary():
    try:
        if not os.path.exists(CRM_DATA_FILE):
            return jsonify([])
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        with open(CRM_DATA_FILE, 'r') as f:
            records = json.load(f)
        recent = [r for r in records if datetime.fromisoformat(r['timestamp']) >= one_week_ago]
        return jsonify(recent)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/clean-old')
def clean_old_records():
    try:
        if not os.path.exists(CRM_DATA_FILE):
            return jsonify({"message": "Nothing to clean."})
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        with open(CRM_DATA_FILE, 'r+') as f:
            records = json.load(f)
            filtered = [r for r in records if datetime.fromisoformat(r['timestamp']) >= thirty_days_ago]
            f.seek(0)
            json.dump(filtered, f, indent=2)
            f.truncate()
        return jsonify({"message": f"Cleaned. {len(records) - len(filtered)} old records removed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload():
    try:
        file = request.files['file']
        filename = file.filename
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(save_path)

        ocr_result = ""
        if filename.lower().endswith(('png', 'jpg', 'jpeg')):
            image = Image.open(save_path)
            ocr_result = pytesseract.image_to_string(image).strip()

            if not os.path.exists(CRM_DATA_FILE):
                with open(CRM_DATA_FILE, 'w') as f:
                    json.dump([], f)

            with open(CRM_DATA_FILE, 'r+') as f:
                data = json.load(f)
                data.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "filename": filename,
                    "text": ocr_result
                })
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()

        return jsonify({
            "message": "Upload complete with OCR scan and CRM sync.",
            "ocrText": ocr_result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").lower()
        if any(phrase in user_message for phrase in DASHBOARD_PHRASES):
            return jsonify({
                "action": "show_dashboard",
                "message": "Pulling up your Goose Sync Dashboard now 📊"
            })
        return jsonify({
            "message": "Pulling up your Goose Sync Dashboard now 📊",
            "action": "show_dashboard"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
