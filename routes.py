import json
import re
import io
import os
from datetime import datetime

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from fuzzywuzzy import fuzz
from PIL import Image
import pytesseract
import httpx
import jwt
import openai

from flask import request, jsonify, render_template, send_file
from config import *
from database import conn, cursor
from utils import *
from auth_utils import token_required


def register_routes(app):

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy"})

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")

    @app.route("/ask", methods=["POST"])
    def ask():
        data = request.get_json()
        question = data.get("query")
        if not question:
            return jsonify({"error": "Query is missing"}), 400

        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            response = openai.ChatCompletion.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4"),
                messages=[{"role": "user", "content": question}]
            )
            reply = response.choices[0].message.content
            return jsonify({"response": reply})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/get-messages", methods=["GET"])
    @token_required
    def get_messages(user_id):
        cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp", (user_id,))
        messages = [{"sender": m[0], "message": m[1], "timestamp": m[2]} for m in cursor.fetchall()]
        return jsonify({"messages": messages})

    @app.route("/save_token", methods=["POST"])
    @token_required
    def save_token(user_id):
        data = request.get_json()
        service = data.get("service")
        token = data.get("token")
        if not service or not token:
            return jsonify({"error": "Service and token are required"}), 400

        cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)", (user_id, service, token))
        conn.commit()
        return jsonify({"status": f"Token saved for {service}"})
    @app.route("/process-ocr", methods=["POST"])
    @token_required
    async def process_ocr(user_id):
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400
        image = request.files['image']

        try:
            img = Image.open(image)
            text = pytesseract.image_to_string(img)

            name = re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", text)
            email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text)
            phone = re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", text)

            contact = {
                "Full Name": name.group(0) if name else "Unknown",
                "Email": email.group(0) if email else "",
                "Work Phone": phone.group(0) if phone else ""
            }

            token = get_token(user_id, "realnex", cursor)
            if token and contact["Email"]:
                df = pd.DataFrame([contact])
                csv = io.StringIO()
                df.to_csv(csv, index=False)
                csv_data = csv.getvalue()

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{REALNEX_API_BASE}/ImportData",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"},
                        data=csv_data
                    )
                sync_status = "Success" if response.status_code == 200 else f"Failed: {response.text}"
            else:
                sync_status = "No token or email"

            return jsonify({
                "parsed_contact": contact,
                "text": text,
                "sync_status": sync_status
            })

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/field-map/save/<name>", methods=["POST"])
    @token_required
    def save_field_mapping(user_id, name):
        data = request.get_json()
        contacts = data.get("contacts", {})
        return jsonify({"status": f"Mapping '{name}' saved", "contacts": contacts})

    @app.route("/field-map/saved/<name>", methods=["GET"])
    @token_required
    def load_field_mapping(user_id, name):
        dummy_mappings = {"contacts": {"Full Name": "name", "Email": "email"}}
        return jsonify(dummy_mappings)

    @app.route("/market-insights", methods=["GET"])
    @token_required
    async def market_insights(user_id):
        cursor.execute("SELECT amount, close_date FROM deals WHERE user_id = ? ORDER BY close_date DESC LIMIT 5", (user_id,))
        deals = cursor.fetchall()

        cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
        activity = cursor.fetchall()

        deal_summary = "\n".join([f"- Amount: ${d[0]}, Close Date: {d[1]}" for d in deals])
        activity_summary = "\n".join([f"- {a[0]} at {a[2]}: {a[1]}" for a in activity])

        prompt = (
            "You are a CRE market analyst. Based on the data, offer 2-3 sentence insights.\n"
            f"Recent Deals:\n{deal_summary}\n\nRecent Activity:\n{activity_summary}"
        )

        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            response = openai.ChatCompletion.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4"),
                messages=[{"role": "system", "content": "You are a CRE analyst."}, {"role": "user", "content": prompt}]
            )
            content = response.choices[0].message.content
            return jsonify({"insight": content})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    @app.route("/generate_report", methods=["POST"])
    @token_required
    def generate_report(user_id):
        report_type = request.json.get("report_type", "activity")

        cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
        logs = cursor.fetchall()
        report_data = {f"Activity {i+1}": f"{log[0]} at {log[2]}: {log[1]}" for i, log in enumerate(logs)}

        pdf = generate_pdf_report(user_id, report_data, f"{report_type.title()} Report", cursor, conn)

        return send_file(
            pdf,
            download_name=f"{report_type}_report_{user_id}.pdf",
            as_attachment=True,
            mimetype='application/pdf'
        )

    @app.route("/duplicates-data", methods=["GET"])
    @token_required
    def duplicates_data(user_id):
        cursor.execute("SELECT id, name, email FROM contacts WHERE user_id = ?", (user_id,))
        contacts = cursor.fetchall()
        duplicates = []

        for i, contact in enumerate(contacts):
            for j, other in enumerate(contacts[i+1:], start=i+1):
                name_similarity = fuzz.token_sort_ratio(contact[1], other[1])
                email_similarity = fuzz.token_sort_ratio(contact[2], other[2])
                if name_similarity > 85 or email_similarity > 90:
                    duplicates.append({
                        "contact1": {"id": contact[0], "name": contact[1], "email": contact[2]},
                        "contact2": {"id": other[0], "name": other[1], "email": other[2]},
                        "name_similarity": name_similarity,
                        "email_similarity": email_similarity
                    })

        return jsonify({"duplicates": duplicates})

    @app.route("/save-settings", methods=["POST"])
    @token_required
    def save_settings(user_id):
        settings = request.get_json()
        try:
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            return jsonify({"status": "Settings saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/settings-data", methods=["GET"])
    @token_required
    def get_settings(user_id):
        try:
            with open('settings.json', 'r') as f:
                settings = json.load(f)
            return jsonify(settings)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    @app.route("/register-webhook", methods=["POST"])
    @token_required
    def register_webhook(user_id):
        data = request.json
        webhook_url = data.get("webhook_url")

        if not webhook_url:
            return jsonify({"error": "Webhook URL is required"}), 400

        if not re.match(r'^https?://', webhook_url):
            return jsonify({"error": "Invalid webhook URL format"}), 400

        cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)", (user_id, webhook_url))
        conn.commit()
        return jsonify({"status": "Webhook registered successfully"})

    @app.route("/test-webhook", methods=["POST"])
    @token_required
    async def test_webhook(user_id):
        cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
        webhook = cursor.fetchone()
        if not webhook:
            return jsonify({"error": "No webhook registered."}), 400

        test_payload = {
            "user_id": user_id,
            "event": "test",
            "message": "This is a test webhook message from Goose Maverick."
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook[0], json=test_payload)
                if response.status_code == 200:
                    return jsonify({"status": "Webhook test successful"})
                return jsonify({"error": f"Webhook returned {response.status_code}: {response.text}"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/", methods=["GET"])
    def public_index():
        return render_template("index.html")

    @app.route("/dashboard", methods=["GET"])
    def public_dashboard():
        return render_template("main_dashboard.html")

    @app.route("/settings", methods=["GET"])
    def public_settings():
        return render_template("settings.html")

    @app.route("/field-map", methods=["GET"])
    def public_fieldmap():
        return render_template("field-map.html")

    @app.route("/ocr", methods=["GET"])
    def public_ocr():
        return render_template("ocr.html")

    @app.route("/deal-trends", methods=["GET"])
    def public_trends():
        return render_template("deal_trends.html")

    @app.route("/activity", methods=["GET"])
    def public_activity():
        return render_template("activity.html")
