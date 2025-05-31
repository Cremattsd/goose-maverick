from flask import jsonify
from email.mime.text import MIMEText
import smtplib
from datetime import datetime

from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
from database import conn, cursor
from utils import log_user_activity

def handle_help_phrases(message, user_id):
    help_phrases = ["i need a human", "more help", "support help", "billing help", "sales support"]
    if any(phrase in message for phrase in help_phrases):
        issue = "General support request"
        to_email = "support@realnex.com"
        if "billing help" in message or "sales support" in message:
            issue = "Billing or sales support request"
            to_email = "sales@realnex.com"

        subject = f"Support Request from User {user_id}"
        body = (
            f"User ID: {user_id}\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Issue: {issue}\n"
            f"Details: {message}\n\n"
            "Please assist this user as soon as possible."
        )
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, to_email, msg.as_string())
            contact_info = (
                "I’ve sent a support request to the RealNex team for you! They’ll get back to you soon. "
                "If you need to reach them directly, here’s their contact info:\n"
                "📞 Phone: (281) 299-3161\n"
                "📧 Email: info@realnex.com (general inquiries), sales@realnex.com (sales/billing), support@realnex.com (support)\n"
                "Hang tight! 🛠️"
            )
            log_user_activity(user_id, "request_support", {"issue": issue, "to_email": to_email}, cursor, conn)
            return jsonify({"answer": contact_info, "tts": contact_info})
        except Exception as e:
            error_message = f"Failed to send support request: {str(e)}. Please try again or contact RealNex directly at (281) 299-3161 or support@realnex.com."
            return jsonify({"answer": error_message, "tts": error_message})
    return None
