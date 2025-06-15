import json
import re
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import jwt
from flask import request, jsonify, render_template, send_file
import httpx
from PIL import Image
import pytesseract
from fuzzywuzzy import fuzz

from config import *
from database import conn, cursor
from utils import *

def register_routes(app):
    """Register all Flask routes except /ask."""
    @app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint for Render to detect the app."""
        return jsonify({"status": "healthy"})
@token_required

    @app.route('/', methods=['GET'])
    @token_required
    def index(user_id):
        logger.info("Main dashboard page accessed.")
        return render_template('main_dashboard.html')

    @app.route('/chat-hub', methods=['GET'])
    @token_required
    def chat_hub(user_id):
        logger.info("Chat hub page accessed.")
@token_required
        return render_template('index.html')

    @app.route('/dashboard', methods=['GET'])
    @token_required
    def dashboard(user_id):
        logger.info("Duplicates dashboard page accessed.")
        return render_template('duplicates_dashboard.html')

    @app.route('/activity', methods=['GET'])
    @token_required
    def activity(user_id):
        logger.info("Activity log page accessed.")
        return render_template('activity.html')

    @app.route('/deal-trends', methods=['GET'])
    @token_required
    def deal_trends(user_id):
        logger.info("Deal trends page accessed.")
        return render_template('deal_trends.html')

    @app.route('/field-map', methods=['GET'])
    @token_required
    def field_map(user_id):
        logger.info("Field mapping editor page accessed.")
        return render_template('field_map.html')

    @app.route('/ocr', methods=['GET'])
    @token_required
    def ocr_page(user_id):
        logger.info("OCR scanner page accessed.")
        return render_template('ocr.html')

    @app.route('/settings', methods=['GET'])
    @token_required
    def settings_page(user_id):
        logger.info("Settings page accessed.")
        return render_template('settings.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Handle user login and issue JWT token."""
        if request.method == 'GET':
            return render_template('login.html')

        data = request.json
        username = data.get('username')
        password = data.get('password')

        if username == 'admin' and password == 'password123':
            user_id = 'default'
            token = jwt.encode({
                'user_id': user_id,
                'user': username,
                'exp': datetime.utcnow() + timedelta(hours=24)
            }, SECRET_KEY, algorithm='HS256')
@token_required
            return jsonify({"token": token})
        return jsonify({"error": "Invalid credentials"}), 401

    @app.route('/save_token', methods=['POST'])
    @token_required
    def save_token(user_id):
        """Save an API token for a user and service."""
        data = request.json
        service = data.get('service')
        token = data.get('token')

        if not service or not token:
            return jsonify({"error": "Service and token are required"}), 400

        cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                       (user_id, service, token))
        conn.commit()
        redis = init_redis()
        if redis:
@token_required
            redis.setex(f"token:{user_id}:{service}", 3600, token)
        log_user_activity(user_id, "save_token", {"service": service}, cursor, conn)
        return jsonify({"status": f"Token for {service} saved successfully"})

    @app.route('/duplicates', methods=['GET'])
    @token_required
    def get_duplicates(user_id):
        """Retrieve duplicate contacts for the user."""
        cursor.execute("SELECT contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        duplicates = cursor.fetchall()
        result = []
        for dup in duplicates:
            result.append({
                "contact_hash": dup[0],
@token_required
                "contact_data": json.loads(dup[1]),
                "timestamp": dup[2]
            })
        return jsonify({"duplicates": result})

    @app.route('/activity_log', methods=['GET'])
    @token_required
    def get_activity_log(user_id):
        """Retrieve the user's activity log."""
        cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
        logs = cursor.fetchall()
        result = [{"action": log[0], "details": json.loads(log[1]), "timestamp": log[2]} for log in logs]
        return jsonify({"activity_log": result})

    @app.route('/save_email_template', methods=['POST'])
    @token_required
    def save_email_template(user_id):
        """Save a custom email template for the user."""
        data = request.json
        template_name = data.get('template_name')
        subject = data.get('subject')
        body = data.get('body')

        if not all([template_name, subject, body]):
            return jsonify({"error": "Template name, subject, and body are required"}), 400

@token_required
        cursor.execute("INSERT INTO email_templates (user_id, template_name, subject, body) VALUES (?, ?, ?, ?)",
                       (user_id, template_name, subject, body))
        conn.commit()
        log_user_activity(user_id, "save_email_template", {"template_name": template_name}, cursor, conn)
        return jsonify({"status": "Email template saved successfully"})

    @app.route('/get_email_templates', methods=['GET'])
    @token_required
    def get_email_templates(user_id):
        """Retrieve all email templates for the user."""
        cursor.execute("SELECT template_name, subject, body FROM email_templates WHERE user_id = ?", (user_id,))
        templates = cursor.fetchall()
        result = [{"template_name": t[0], "subject": t[1], "body": t[2]} for t in templates]
        return jsonify({"templates": result})

    @app.route('/schedule_task', methods=['POST'])
    @token_required
    def schedule_task(user_id):
        """Schedule a task like sending a RealBlast or generating a report."""
        data = request.json
        task_type = data.get('task_type')
        task_data = data.get('task_data')
        schedule_time = data.get('schedule_time')

        if not all([task_type, task_data, schedule_time]):
            return jsonify({"error": "Task type, data, and schedule time are required"}), 400
@token_required

        cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, task_type, json.dumps(task_data), schedule_time, "pending"))
        conn.commit()
        log_user_activity(user_id, "schedule_task", {"task_type": task_type, "schedule_time": schedule_time}, cursor, conn)
        return jsonify({"status": "Task scheduled successfully"})

    @app.route('/generate_report', methods=['POST'])
    @token_required
    def generate_report(user_id):
        """Generate a PDF report based on user data."""
        data = request.json
        report_type = data.get('report_type', 'activity')

        if report_type == 'activity':
            cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
            logs = cursor.fetchall()
            report_data = {}
            for i, log in enumerate(logs, 1):
                report_data[f"Activity {i}"] = f"{log[0]} at {log[2]}: {json.loads(log[1])}"
            title = "Recent Activity Report"

        pdf_output = generate_pdf_report(user_id, report_data, title, cursor, conn)
        log_user_activity(user_id, "generate_report", {"report_type": report_type}, cursor, conn)
@token_required

        return send_file(
            pdf_output,
            attachment_filename=f"{report_type}_report_{user_id}.pdf",
            as_attachment=True,
            mimetype='application/pdf'
        )

    @app.route('/save-message', methods=['POST'])
    @token_required
    def save_message(user_id):
        """Save a chat message to the database."""
        data = request.json
@token_required
        sender = data.get('sender')
        message = data.get('message')
        timestamp = datetime.now().isoformat()

        cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                       (user_id, sender, message, timestamp))
        conn.commit()
        return jsonify({"status": "Message saved"})

@token_required
    @app.route('/get-messages', methods=['GET'])
    @token_required
    def get_messages(user_id):
        """Retrieve chat messages for the user."""
        cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp",
                       (user_id,))
        messages = cursor.fetchall()
        result = [{"sender": msg[0], "message": msg[1], "timestamp": msg[2]} for msg in messages]
        return jsonify({"messages": result})

    @app.route('/dashboard-data', methods=['GET'])
    @token_required
    def dashboard_data(user_id):
        """Fetch data for the main dashboard (lead scores) with caching."""
        cache_key = f"dashboard_data:{user_id}"
        redis = init_redis()
        if redis:
            cached_data = redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for {cache_key}")
                return jsonify(json.loads(cached_data))

@token_required
        lead_scores = [
            {"contact_id": "contact1", "score": 85},
            {"contact_id": "contact2", "score": 92}
        ]
        data = {"lead_scores": lead_scores}

        if redis:
            redis.setex(cache_key, 300, json.dumps(data))
            logger.debug(f"Cache set for {cache_key}")
        return jsonify(data)

    @app.route('/import-stats', methods=['GET'])
    @token_required
    def import_stats(user_id):
        """Fetch import statistics with caching."""
        cache_key = f"import_stats:{user_id}"
        redis = init_redis()
        if redis:
            cached_data = redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for {cache_key}")
                return jsonify(json.loads(cached_data))
@token_required

        stats = {
            "total_imports": 150,
            "successful_imports": 140,
            "duplicates_detected": 10
        }

        if redis:
            redis.setex(cache_key, 300, json.dumps(stats))
            logger.debug(f"Cache set for {cache_key}")
        return jsonify(stats)

    @app.route('/mission-summary', methods=['GET'])
    @token_required
    def mission_summary(user_id):
        """Fetch a mission summary with caching."""
        cache_key = f"mission_summary:{user_id}"
        redis = init_redis()
@token_required
        if redis:
            cached_data = redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for {cache_key}")
                return jsonify(json.loads(cached_data))

        summary = {"summary": "Mission Summary: Synced 150 contacts, detected 10 duplicates, predicted 2 deals."}

        if redis:
            redis.setex(cache_key, 300, json.dumps(summary))
            logger.debug(f"Cache set for {cache_key}")
        return jsonify(summary)

    @app.route('/market-insights', methods=['GET'])
    @token_required
    async def market_insights(user_id):
        """Generate AI-powered market insights using OpenAI."""
        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

        cursor.execute("SELECT amount, close_date FROM deals WHERE user_id = ? ORDER BY close_date DESC LIMIT 5", (user_id,))
        deals = cursor.fetchall()
        deal_context = "Recent Deals:\n"
        for deal in deals:
            deal_context += f"- Amount: ${deal[0]}, Close Date: {deal[1]}\n"

        cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user_id,))
        activities = cursor.fetchall()
        activity_context = "Recent Activity:\n"
        for activity in activities:
            activity_context += f"- Action: {activity[0]}, Details: {activity[1]}, Timestamp: {activity[2]}\n"

        prompt = (
            f"You are a commercial real estate market analyst. Based on the following data, provide a brief market insight or trend prediction for the user:\n\n"
            f"{deal_context}\n"
            f"{activity_context}\n"
            "Provide a concise insight (2-3 sentences) about the market trends or opportunities the user should be aware of."
        )

        try:
@token_required
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a commercial real estate market analyst."},
                    {"role": "user", "content": prompt}
                ]
            )
            insight = response.choices[0].message.content
            log_user_activity(user_id, "generate_market_insight", {"insight": insight}, cursor, conn)
            return jsonify({"insight": insight})
        except Exception as e:
            logger.error(f"Failed to generate market insight: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/duplicates-data', methods=['GET'])
    @token_required
    def duplicates_data(user_id):
        """Fetch duplicate contacts based on fuzzy matching from contacts table with caching."""
        cache_key = f"duplicates_data:{user_id}"
        redis = init_redis()
        if redis:
            cached_data = redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for {cache_key}")
                return jsonify(json.loads(cached_data))

        cursor.execute("SELECT id, name, email FROM contacts WHERE user_id = ?", (user_id,))
        contacts = cursor.fetchall()
        duplicates = []

        for i, contact in enumerate(contacts):
            for j, other in enumerate(contacts[i+1:], start=i+1):
                name_similarity = fuzz.token_sort_ratio(contact[1], other[1])
@token_required
                email_similarity = fuzz.token_sort_ratio(contact[2], other[2])
                if name_similarity > 85 or email_similarity > 90:
                    duplicates.append({
                        "contact1": {"id": contact[0], "name": contact[1], "email": contact[2]},
                        "contact2": {"id": other[0], "name": other[1], "email": other[2]},
                        "name_similarity": name_similarity,
                        "email_similarity": email_similarity
                    })

        data = {"duplicates": duplicates}
        if redis:
            redis.setex(cache_key, 300, json.dumps(data))
            logger.debug(f"Cache set for {cache_key}")
        return jsonify(data)

    @app.route('/deal-trends-data', methods=['GET'])
    @token_required
    def deal_trends_data(user_id):
        """Fetch and predict deal trends with caching."""
        cache_key = f"deal_trends_data:{user_id}"
        redis = init_redis()
        if redis:
            cached_data = redis.get(cache_key)
            if cached_data:
                logger.debug(f"Cache hit for {cache_key}")
                return jsonify(json.loads(cached_data))

        cursor.execute("SELECT amount, close_date FROM deals WHERE user_id = ? ORDER BY close_date", (user_id,))
        deals = cursor.fetchall()

        if not deals:
            data = {"trends": [], "predictions": []}
            if redis:
                redis.setex(cache_key, 300, json.dumps(data))
            return jsonify(data)

        dates = [datetime.strptime(deal[1], '%Y-%m-%d').timestamp() for deal in deals]
        amounts = [deal[0] for deal in deals]

        X = np.array(dates).reshape(-1, 1)
        y = np.array(amounts)

        model = LinearRegression()
@token_required
        model.fit(X, y)

        last_date = dates[-1]
        future_dates = [last_date + i * 30 * 24 * 60 * 60 for i in range(1, 4)]
        future_X = np.array(future_dates).reshape(-1, 1)
        predictions = model.predict(future_X).tolist()
@token_required

        trends = [{"date": deal[1], "amount": deal[0]} for deal in deals]
        future_predictions = [{"date": datetime.fromtimestamp(fd).strftime('%Y-%m-%d'), "amount": int(pred)} for fd, pred in zip(future_dates, predictions)]

        data = {"trends": trends, "predictions": future_predictions}
        if redis:
            redis.setex(cache_key, 300, json.dumps(data))
            logger.debug(f"Cache set for {cache_key}")
@token_required
        return jsonify(data)

    @app.route('/field-map/saved/<name>', methods=['GET'])
    @token_required
    def load_field_mapping(user_id, name):
        """Load a saved field mapping."""
        mappings = {"contacts": {"Full Name": "name", "Email": "email"}}
        return jsonify(mappings.get(name, {"contacts": {}}))

    @app.route('/field-map/save/<name>', methods=['POST'])
    @token_required
    def save_field_mapping(user_id, name):
        """Save a field mapping."""
        data = request.json
        contacts = data.get('contacts', {})
        logger.info(f"Saved mapping: {name} - {contacts}")
        return jsonify({"status": "Mapping saved"})

    @app.route('/process-ocr', methods=['POST'])
    @token_required
    async def process_ocr(user_id):
        """Process an image with OCR, parse text, and auto-sync to RealNex."""
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image = request.files['image']
        try:
            img = Image.open(image)
            text = pytesseract.image_to_string(img)

            name_pattern = r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|[A-Z][a-z]+)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
            email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            phone_pattern = r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"

            name = re.search(name_pattern, text)
            email = re.search(email_pattern, text)
            phone = re.search(phone_pattern, text)

            contact = {
                "Full Name": name.group(0) if name else "Unknown",
                "Email": email.group(0) if email else "",
                "Work Phone": phone.group(0) if phone else ""
            }

            details = {"filename": image.filename, "extracted_text": text, "parsed_contact": contact}
            timestamp = datetime.now().isoformat()
            cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, "process_ocr", json.dumps(details), timestamp))
            conn.commit()

            token = get_token(user_id, "realnex", cursor)
            if token and contact["Email"]:
                contacts = [contact]
                df = pd.DataFrame(contacts)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_data = csv_buffer.getvalue()

                async with httpx.AsyncClient() as client:
@token_required
                    response = await client.post(
                        f"{REALNEX_API_BASE}/ImportData",
                        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                        data=csv_data
                    )

                if response.status_code == 200:
                    cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                   (contact["Email"], contact["Full Name"], contact["Email"], user_id))
                    conn.commit()
                    log_user_activity(user_id, "auto_sync_ocr_contact", {"contact": contact}, cursor, conn)
@token_required
                    return jsonify({"text": text, "parsed_contact": contact, "sync_status": "Contact synced to RealNex"})
                else:
                    return jsonify({"text": text, "parsed_contact": contact, "sync_status": f"Failed to sync: {response.text}"})
            return jsonify({"text": text, "parsed_contact": contact, "sync_status": "No RealNex token or email found"})
        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/settings-data', methods=['GET'])
    @token_required
    def get_settings(user_id):
        """Fetch current settings."""
@token_required
        try:
            with open('settings.json', 'r') as f:
                settings = json.load(f)
            return jsonify(settings)
        except Exception as e:
            logger.error(f"Failed to load settings: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/save-settings', methods=['POST'])
    @token_required
    def save_settings(user_id):
        """Save updated settings."""
        try:
            settings = request.json
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            return jsonify({"status": "Settings saved"})
        except Exception as e:
            logger.error(f"Failed to save settings: {str(e)}")
@token_required
            return jsonify({"error": str(e)}), 500

    @app.route('/register-webhook', methods=['POST'])
    @token_required
    async def register_webhook(user_id):
        """Register a webhook URL for the user to receive deal alerts."""
        data = request.json
        webhook_url = data.get('webhook_url')

        if not webhook_url:
            return jsonify({"error": "Webhook URL is required"}), 400

        if not re.match(r'^https?://', webhook_url):
            return jsonify({"error": "Invalid webhook URL format"}), 400

        cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                       (user_id, webhook_url))
        conn.commit()

        log_user_activity(user_id, "register_webhook", {"webhook_url": webhook_url}, cursor, conn)
        return jsonify({"status": "Webhook registered successfully"})

    @app.route('/test-webhook', methods=['POST'])
    @token_required
    async def test_webhook(user_id):
        """Test the registered webhook by sending a sample payload."""
        cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
        webhook = cursor.fetchone()
        if not webhook:
            return jsonify({"error": "No webhook registered. Register one using /register-webhook."}), 400

        webhook_url = webhook[0]
        test_data = {
            "user_id": user_id,
            "event": "test",
            "message": "This is a test webhook payload from Matty’s Maverick & Goose!"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(webhook_url, json=test_data)
                if response.status_code == 200:
                    log_user_activity(user_id, "test_webhook", {"webhook_url": webhook_url, "status": "success"}, cursor, conn)
                    return jsonify({"status": "Test webhook sent successfully"})
                else:
                    log_user_activity(user_id, "test_webhook", {"webhook_url": webhook_url, "status": "failed", "response": response.text}, cursor, conn)
                    return jsonify({"error": f"Webhook test failed: {response.text}"}), 400
            except Exception as e:
                log_user_activity(user_id, "test_webhook", {"webhook_url": webhook_url, "status": "error", "error": str(e)}, cursor, conn)
                return jsonify({"error": f"Webhook test error: {str(e)}"}), 500