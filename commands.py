import json
import re
import smtplib
import base64
from email.mime.text import MIMEText
from datetime import datetime
import pandas as pd
import openai
from mailchimp_marketing import Client as MailchimpClient
from io import StringIO
import httpx

from config import *
from database import conn, cursor
from utils import *

# Initialize OpenAI client
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully.")
except Exception as e:
    logger.error(f"OpenAI client initialization failed: {e}")
    openai_client = None

# Global Mailchimp client
mailchimp = None

def register_commands(app, socketio):
    """Register the /ask endpoint for natural language commands."""
    @app.route('/ask', methods=['POST'])
    @token_required
    async def ask(user_id):
        """Handle natural language queries for CRE tasks."""
        data = request.json
        message = data.get('message', '').lower()

        cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        points = user_data[0] if user_data else 0
        email_credits = user_data[1] if user_data else 0
        has_msa = user_data[2] if user_data else 0

        settings = get_user_settings(user_id, cursor, conn)
        onboarding_steps = ["save_settings", "sync_crm_data", "send_realblast", "send_training_reminder"]
        completed_steps = []
        for step in onboarding_steps:
            cursor.execute("SELECT completed FROM user_onboarding WHERE user_id = ? AND step = ?", (user_id, step))
            result = cursor.fetchone()
            if result and result[0] == 1:
                completed_steps.append(step)

        original_message = message
        if settings["language"] != "en":
            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": f"Translate this {settings['language']} text to English."},
                        {"role": "user", "content": message}
                    ]
                )
                message = response.choices[0].message.content.lower()
                log_user_activity(user_id, "translate_message", {"from": settings["language"], "to": "en", "original": original_message, "translated": message}, cursor, conn)
            except Exception as e:
                logger.error(f"Translation failed: {e}")

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

        if 'draft an email' in message:
            campaign_type = "RealBlast" if "realblast" in message else "Mailchimp"
            subject = "Your CRE Update"
            audience_id = None
            content = None

            if "realblast" in message:
                answer = "Let’s draft a RealBlast email! What’s the subject? (e.g., 'New Property Listing') Or say 'suggest a subject' to get ideas."
                return jsonify({"answer": answer, "tts": answer})
            else:
                answer = "Let’s draft a Mailchimp email! What’s the subject? (e.g., 'Your CRE Update') Or say 'suggest a subject' to get ideas."
                return jsonify({"answer": answer, "tts": answer})

        elif 'suggest a subject' in message:
            if not settings["subject_generator_enabled"]:
                answer = "Subject line generator is disabled in settings. Enable it to get suggestions! ⚙️"
                return jsonify({"answer": answer, "tts": answer})

            campaign_type = "RealBlast" if "realblast" in message else "Mailchimp"
            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are an expert in email marketing for commercial real estate."},
                        {"role": "user", "content": f"Generate a catchy subject line for a {campaign_type} email campaign."}
                    ]
                )
                subject = response.choices[0].message.content.strip()
                answer = f"Suggested subject: '{subject}'. Does this work? Say the subject to use it, or provide your own!"
                log_user_activity(user_id, "suggest_subject", {"campaign_type": campaign_type, "subject": subject}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            except Exception as e:
                answer = f"Failed to generate subject line: {str(e)}. Try providing your own subject."
                return jsonify({"answer": answer, "tts": answer})

        elif 'subject' in message and 'realblast' in message:
            subject = message.split('subject')[-1].strip()
            answer = f"Got the subject: '{subject}'. Which RealNex group ID should this go to? (e.g., 'group123')"
            return jsonify({"answer": answer, "tts": answer})

        elif 'group id' in message:
            audience_id = message.split('group id')[-1].strip()
            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                        {"role": "user", "content": f"Draft a RealBlast email for group {audience_id} with subject 'Your CRE Update'."}
                    ]
                )
                content = response.choices[0].message.content
                answer = f"Here’s your RealBlast email for group {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your RealNex RealBlast setup. 📧"
                log_user_activity(user_id, "draft_email", {"type": "RealBlast", "group_id": audience_id}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            except Exception as e:
                answer = f"Failed to draft email: {str(e)}. Try again."
                return jsonify({"answer": answer, "tts": answer})

        elif 'subject' in message and 'mailchimp' in message:
            subject = message.split('subject')[-1].strip()
            answer = f"Got the subject: '{subject}'. Which Mailchimp audience ID should this go to? (e.g., 'audience456')"
            return jsonify({"answer": answer, "tts": answer})

        elif 'audience id' in message:
            audience_id = message.split('audience id')[-1].strip()
            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a professional email writer for a commercial real estate chatbot."},
                        {"role": "user", "content": f"Draft a Mailchimp email for audience {audience_id} with subject 'Your CRE Update'."}
                    ]
                )
                content = response.choices[0].message.content
                answer = f"Here’s your Mailchimp email for audience {audience_id}:\nSubject: Your CRE Update\nContent:\n{content}\n\nCopy and paste this into your Mailchimp campaign setup. 📧"
                log_user_activity(user_id, "draft_email", {"type": "Mailchimp", "audience_id": audience_id}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            except Exception as e:
                answer = f"Failed to draft email: {str(e)}. Try again."
                return jsonify({"answer": answer, "tts": answer})

        elif 'send realblast' in message:
            group_id = None
            campaign_content = None
            if 'group' in message:
                group_id = message.split('group')[-1].strip().split()[0]
            if 'content' in message:
                campaign_content = message.split('content')[-1].strip()

            if not group_id or not campaign_content:
                answer = "To send a RealBlast, I need the group ID and campaign content. Say something like 'send realblast to group group123 with content Check out this property!'. What’s the group ID and content? 📧"
                return jsonify({"answer": answer, "tts": answer})

            token = get_token(user_id, "realnex", cursor)
            if not token:
                answer = "Please fetch your RealNex JWT token in Settings to send a RealBlast. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            if not twilio_client:
                return jsonify({"error": "Twilio client not initialized. Check server logs for details."}), 500

            two_fa_code = data.get('two_fa_code')
            if not two_fa_code:
                if not send_2fa_code(user_id, cursor, conn):
                    return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
                answer = "2FA code sent to your phone. Please provide the code to proceed with sending the RealBlast. 🔒"
                return jsonify({"answer": answer, "tts": answer})

            if not check_2fa(user_id, two_fa_code, cursor, conn):
                answer = "Invalid 2FA code. Try again."
                return jsonify({"answer": answer, "tts": answer})

            if has_msa:
                cursor.execute("UPDATE user_points SET has_msa = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                socketio.emit('msa_update', {'user_id': user_id, 'message': "Used your free RealBlast MSA! Nice work! 🚀"})
            elif email_credits > 0:
                email_credits -= 1
                cursor.execute("UPDATE user_points SET email_credits = ? WHERE user_id = ?", (email_credits, user_id))
                conn.commit()
                socketio.emit('credits_update', {'user_id': user_id, 'email_credits': email_credits, 'message': f"Used 1 email credit for RealBlast. You have {email_credits} credits left. 📧"})
            else:
                answer = "You need email credits or a free RealBlast MSA to send a RealBlast! Earn 1000 points to unlock 1000 credits, or complete onboarding for a free MSA. Check your status with 'my status'. 🚀"
                return jsonify({"answer": answer, "tts": answer})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REALNEX_API_BASE}/RealBlasts",
                    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                    json={"group_id": group_id, "content": campaign_content}
                )

            if response.status_code == 200:
                points, email_credits, has_msa, points_message = award_points(user_id, 15, "sending a RealNex RealBlast", cursor, conn)
                socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"RealBlast sent to group {group_id}!"})
                update_onboarding(user_id, "send_realblast", cursor, conn)
                answer = f"RealBlast sent to group {group_id}! 📧 {points_message}"
                if settings["sms_notifications"] and twilio_client:
                    twilio_client.messages.create(
                        body=f"RealBlast sent to group {group_id}! {points_message}",
                        from_=TWILIO_PHONE,
                        to="+1234567890"
                    )
                log_user_activity(user_id, "send_realblast", {"group_id": group_id}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            answer = f"Failed to send RealBlast: {response.text}"
            return jsonify({"answer": answer, "tts": answer})

        elif 'send mailchimp campaign' in message:
            audience_id = None
            campaign_content = None
            if 'audience' in message:
                audience_id = message.split('audience')[-1].strip().split()[0]
            if 'content' in message:
                campaign_content = message.split('content')[-1].strip()

            if not audience_id or not campaign_content:
                answer = "To send a Mailchimp campaign, I need the audience ID and campaign content. Say something like 'send mailchimp campaign to audience audience456 with content Check out this property!'. What’s the audience ID and content? 📧"
                return jsonify({"answer": answer, "tts": answer})

            token = get_token(user_id, "mailchimp", cursor)
            if not token:
                answer = "Please add your Mailchimp API key in Settings to send a Mailchimp campaign. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            global mailchimp
            mailchimp = MailchimpClient()
            mailchimp.set_config({"api_key": token, "server": MAILCHIMP_SERVER_PREFIX})

            if not twilio_client:
                return jsonify({"error": "Twilio client not initialized. Check server logs for details."}), 500

            two_fa_code = data.get('two_fa_code')
            if not two_fa_code:
                if not send_2fa_code(user_id, cursor, conn):
                    return jsonify({"error": "Failed to send 2FA code. Ensure user is registered for 2FA."}), 400
                answer = "2FA code sent to your phone. Please provide the code to proceed with sending the Mailchimp campaign. 🔒"
                return jsonify({"answer": answer, "tts": answer})

            if not check_2fa(user_id, two_fa_code, cursor, conn):
                answer = "Invalid 2FA code. Try again."
                return jsonify({"answer": answer, "tts": answer})

            try:
                campaign = mailchimp.campaigns.create({
                    "type": "regular",
                    "recipients": {"list_id": audience_id},
                    "settings": {
                        "subject_line": "Your CRE Campaign",
                        "from_name": "Matty’s Maverick & Goose",
                        "reply_to": "noreply@example.com"
                    }
                })
                campaign_id = campaign.get("id")
                mailchimp.campaigns.set_content(campaign_id, {"html": campaign_content})
                mailchimp.campaigns.actions.send(campaign_id)
                socketio.emit('campaign_sent', {'user_id': user_id, 'message': f"Mailchimp campaign sent to audience {audience_id}!"})
                answer = f"Mailchimp campaign sent to audience {audience_id}! 📧"
                if settings["email_notifications"]:
                    msg = MIMEText(f"Mailchimp campaign sent to audience {audience_id}!")
                    msg['Subject'] = "Campaign Sent Notification"
                    msg['From'] = SMTP_USER
                    msg['To'] = "user@example.com"
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SMTP_USER, SMTP_PASSWORD)
                        server.sendmail(SMTP_USER, "user@example.com", msg.as_string())
                log_user_activity(user_id, "send_mailchimp_campaign", {"audience_id": audience_id}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            except Exception as e:
                answer = f"Failed to send Mailchimp campaign: {str(e)}"
                return jsonify({"answer": answer, "tts": answer})

        elif 'sync crm data' in message:
            token = get_token(user_id, "realnex", cursor)
            if not token:
                answer = "Please fetch your RealNex JWT token in Settings to sync CRM data. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            zoominfo_token = get_token(user_id, "zoominfo", cursor)
            apollo_token = get_token(user_id, "apollo", cursor)

            zoominfo_contacts = []
            if zoominfo_token:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.zoominfo.com/v1/contacts",
                        headers={"Authorization": f"Bearer {zoominfo_token}"}
                    )
                if response.status_code == 200:
                    zoominfo_contacts = response.json().get("contacts", [])
                else:
                    answer = f"Failed to fetch ZoomInfo contacts: {response.text}. Check your ZoomInfo token in Settings."
                    return jsonify({"answer": answer, "tts": answer})

            apollo_contacts = []
            if apollo_token:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.apollo.io/v1/contacts",
                        headers={"Authorization": f"Bearer {apollo_token}"}
                    )
                if response.status_code == 200:
                    apollo_contacts = response.json().get("contacts", [])
                else:
                    answer = f"Failed to fetch Apollo.io contacts: {response.text}. Check your Apollo.io token in Settings."
                    return jsonify({"answer": answer, "tts": answer})

            contacts = []
            seen_hashes = set()
            for contact in zoominfo_contacts + apollo_contacts:
                contact_hash = hash_contact(contact)
                if contact_hash in seen_hashes:
                    log_duplicate(user_id, contact, cursor, conn)
                    continue
                seen_hashes.add(contact_hash)
                formatted_contact = {
                    "Full Name": contact.get("name", ""),
                    "First Name": contact.get("first_name", ""),
                    "Last Name": contact.get("last_name", ""),
                    "Company": contact.get("company", ""),
                    "Address1": contact.get("address", ""),
                    "City": contact.get("city", ""),
                    "State": contact.get("state", ""),
                    "Postal Code": contact.get("zip", ""),
                    "Work Phone": contact.get("phone", ""),
                    "Email": contact.get("email", "")
                }
                contacts.append(formatted_contact)

            if contacts:
                df = pd.DataFrame(contacts)
                csv_buffer = StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_data = csv_buffer.getvalue()

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{REALNEX_API_BASE}/ImportData",
                        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                        data=csv_data
                    )

                if response.status_code == 200:
                    points, email_credits, has_msa, points_message = award_points(user_id, 10, "bringing in data", cursor, conn)
                    update_onboarding(user_id, "sync_crm_data", cursor, conn)
                    for contact in contacts:
                        cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                       (contact["Email"], contact["Full Name"], contact["Email"], user_id))
                    conn.commit()
                    answer = f"Synced {len(contacts)} contacts into RealNex. 📇 {points_message}"
                    log_user_activity(user_id, "sync_crm_data", {"num_contacts": len(contacts)}, cursor, conn)
                    return jsonify({"answer": answer, "tts": answer})
                answer = f"Failed to import contacts into RealNex: {response.text}"
                return jsonify({"answer": answer, "tts": answer})
            answer = "No contacts to sync."
            return jsonify({"answer": answer, "tts": answer})

        elif 'sync contacts' in message:
            google_token = data.get('google_token')
            if not google_token:
                answer = "I need a Google token to sync contacts. Say something like 'sync contacts with google token your_token_here'. What’s your Google token?"
                return jsonify({"answer": answer, "tts": answer})

            token = get_token(user_id, "realnex", cursor)
            if not token:
                answer = "Please fetch your RealNex JWT token in Settings to sync contacts. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(
                        "https://people.googleapis.com/v1/people/me/connections",
                        headers={"Authorization": f"Bearer {google_token}"},
                        params={"personFields": "names,emailAddresses,phoneNumbers"}
                    )
                    if response.status_code != 200:
                        answer = f"Failed to fetch Google contacts: {response.text}. Check your Google token in Settings."
                        return jsonify({"answer": answer, "tts": answer})
                    google_contacts = response.json().get("connections", [])
                except Exception as e:
                    answer = f"Error fetching Google contacts: {str(e)}. Check your Google token or try again."
                    return jsonify({"answer": answer, "tts": answer})

            contacts = []
            seen_hashes = set()
            for contact in google_contacts:
                name = contact.get("names", [{}])[0].get("displayName", "Unknown")
                email = contact.get("emailAddresses", [{}])[0].get("value", "")
                phone = contact.get("phoneNumbers", [{}])[0].get("value", "")

                formatted_contact = {
                    "Full Name": name,
                    "Email": email,
                    "Work Phone": phone
                }
                contact_hash = hash_contact(formatted_contact)
                if contact_hash in seen_hashes:
                    log_duplicate(user_id, formatted_contact, cursor, conn)
                    continue
                seen_hashes.add(contact_hash)
                contacts.append(formatted_contact)

            if contacts:
                df = pd.DataFrame(contacts)
                csv_buffer = StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_data = csv_buffer.getvalue()

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{REALNEX_API_BASE}/ImportData",
                        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'text/csv'},
                        data=csv_data
                    )

                    if response.status_code == 200:
                        points, email_credits, has_msa, points_message = award_points(user_id, 10, "syncing Google contacts", cursor, conn)
                        update_onboarding(user_id, "sync_crm_data", cursor, conn)
                        for contact in contacts:
                            cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                           (contact["Email"], contact["Full Name"], contact["Email"], user_id))
                        conn.commit()
                        answer = f"Synced {len(contacts)} Google contacts into RealNex. 📇 {points_message}"
                        log_user_activity(user_id, "sync_google_contacts", {"num_contacts": len(contacts)}, cursor, conn)
                        return jsonify({"answer": answer, "tts": answer})
                    answer = f"Failed to import Google contacts into RealNex: {response.text}"
                    return jsonify({"answer": answer, "tts": answer})
            answer = "No Google contacts to sync."
            return jsonify({"answer": answer, "tts": answer})elif 'predict deal' in message:
            deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
            sq_ft = None
            if 'square footage' in message or 'sq ft' in message:
                sq_ft = re.search(r'\d+', message)
                sq_ft = int(sq_ft.group()) if sq_ft else None

            if not deal_type or not sq_ft:
                answer = "To predict a deal, I need the deal type (LeaseComp or SaleComp) and square footage. Say something like 'predict deal for LeaseComp with 5000 sq ft'. What’s the deal type and square footage? 🔮"
                return jsonify({"answer": answer, "tts": answer})

            token = get_token(user_id, "realnex", cursor)
            if not token:
                answer = "Please fetch your RealNex JWT token in Settings to predict a deal. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            historical_data = await get_realnex_data(user_id, f"{deal_type}s", cursor)
            if not historical_data:
                answer = "No historical data available for prediction."
                return jsonify({"answer": answer, "tts": answer})

            X = []
            y = []
            prediction = 0
            if deal_type == "LeaseComp":
                for item in historical_data:
                    X.append([item.get("sq_ft", 0)])
                    y.append(item.get("rent_month", 0))
                model = LinearRegression()
                model.fit(X, y)
                prediction = model.predict([[sq_ft]])[0]
                answer = f"Predicted rent for {sq_ft} sq ft: ${prediction:.2f}/month. 🔮"
                chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type, cursor, conn)
                chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
                answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
                cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                               (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
                conn.commit()
                log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction}, cursor, conn)
                tts = f"Predicted rent for {sq_ft} square feet: ${prediction:.2f} per month."
            elif deal_type == "SaleComp":
                for item in historical_data:
                    X.append([item.get("sq_ft", 0)])
                    y.append(item.get("sale_price", 0))
                model = LinearRegression()
                model.fit(X, y)
                prediction = model.predict([[sq_ft]])[0]
                answer = f"Predicted sale price for {sq_ft} sq ft: ${prediction:.2f}. 🔮"
                chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type, cursor, conn)
                chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
                answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
                cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                               (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
                conn.commit()
                log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction}, cursor, conn)
                tts = f"Predicted sale price for {sq_ft} square feet: ${prediction:.2f}."

            cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
            alert = cursor.fetchone()
            if alert:
                threshold, alert_deal_type = alert
                if (alert_deal_type == "Any" or alert_deal_type == deal_type) and prediction > threshold:
                    cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
                    webhook = cursor.fetchone()
                    if webhook:
                        webhook_url = webhook[0]
                        alert_data = {
                            "user_id": user_id,
                            "deal_type": deal_type,
                            "prediction": prediction,
                            "threshold": threshold,
                            "message": f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}."
                        }
                        async with httpx.AsyncClient() as client:
                            try:
                                await client.post(webhook_url, json=alert_data)
                                log_user_activity(user_id, "trigger_webhook", {"webhook_url": webhook_url, "data": alert_data}, cursor, conn)
                            except Exception as e:
                                logger.error(f"Failed to trigger webhook: {str(e)}")
                    if settings["sms_notifications"] and twilio_client:
                        twilio_client.messages.create(
                            body=f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.",
                            from_=TWILIO_PHONE,
                            to="+1234567890"
                        )
                    if settings["email_notifications"]:
                        msg = MIMEText(f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.")
                        msg['Subject'] = "Deal Alert Notification"
                        msg['From'] = SMTP_USER
                        msg['To'] = "user@example.com"
                        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                            server.starttls()
                            server.login(SMTP_USER, SMTP_PASSWORD)
                            server.sendmail(SMTP_USER, "user@example.com", msg.as_string())

            return jsonify({"answer": answer, "tts": tts})

        elif 'negotiate deal' in message:
            deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
            sq_ft = None
            offered_value = None
            if 'square footage' in message or 'sq ft' in message:
                sq_ft = re.search(r'square footage\s*(\d+)|sq ft\s*(\d+)', message)
                sq_ft = int(sq_ft.group(1) or sq_ft.group(2)) if sq_ft else None
            if 'offered' in message:
                offered_value = re.search(r'offered\s*\$\s*([\d.]+)', message)
                offered_value = float(offered_value.group(1)) if offered_value else None

            if not deal_type or not sq_ft or not offered_value:
                answer = "To negotiate a deal, I need the deal type (LeaseComp or SaleComp), square footage, and offered value. Say something like 'negotiate deal for LeaseComp with 5000 sq ft offered $5000'. What’s the deal type, square footage, and offered value? 🤝"
                return jsonify({"answer": answer, "tts": answer})

            token = get_token(user_id, "realnex", cursor)
            if not token:
                answer = "Please fetch your RealNex JWT token in Settings to negotiate a deal. 🔑"
                return jsonify({"answer": answer, "tts": answer})

            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

            historical_data = await get_realnex_data(user_id, f"{deal_type}s", cursor)
            if not historical_data:
                answer = "No historical data available for negotiation."
                return jsonify({"answer": answer, "tts": answer})

            prompt = (
                f"You are a commercial real estate negotiation expert. Based on the following historical {deal_type} data, "
                f"suggest a counteroffer for a property with {sq_ft} square feet, where the offered value is ${offered_value} "
                f"({'per month' if deal_type == 'LeaseComp' else 'total'}). Historical data (square footage, value):\n"
            )
            for item in historical_data:
                sq_ft_value = item.get("sq_ft", 0)
                value = item.get("rent_month", 0) if deal_type == "LeaseComp" else item.get("sale_price", 0)
                prompt += f"- {sq_ft_value} sq ft: ${value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
            prompt += "Provide a counteroffer with a confidence score (0-100) and a brief explanation."

            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a commercial real estate negotiation expert."},
                        {"role": "user", "content": prompt}
                    ]
                )
                ai_response = response.choices[0].message.content

                counteroffer_match = re.search(r'Counteroffer: \$([\d.]+)', ai_response)
                confidence_match = re.search(r'Confidence: (\d+)%', ai_response)
                explanation_match = re.search(r'Explanation: (.*?)(?:\n|$)', ai_response)

                counteroffer = float(counteroffer_match.group(1)) if counteroffer_match else offered_value * 1.1
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else "Based on historical data trends."

                answer = (
                    f"Negotiation Suggestion for {deal_type}:\n"
                    f"Offered: ${offered_value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                    f"Counteroffer: ${round(counteroffer, 2)} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                    f"Confidence: {confidence}%\n"
                    f"Explanation: {explanation}\n"
                    f"Ready to close this deal? 🤝"
                )
                log_user_activity(user_id, "negotiate_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "offered_value": offered_value, "counteroffer": counteroffer}, cursor, conn)
                return jsonify({"answer": answer, "tts": answer})
            except Exception as e:
                answer = f"Failed to negotiate deal: {str(e)}. Try again."
                return jsonify({"answer": answer, "tts": answer})

        elif 'notify me of new deals over' in message:
            if not settings["deal_alerts_enabled"]:
                answer = "Deal alerts are disabled in settings. Enable them to set notifications! ⚙️"
                return jsonify({"answer": answer, "tts": answer})

            threshold = re.search(r'over\s*\$\s*([\d.]+)', message)
            threshold = float(threshold.group(1)) if threshold else None
            deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else "Any"

            if not threshold:
                answer = "Please specify a deal value threshold, e.g., 'notify me of new deals over $5000'. What’s the threshold? 🔔"
                return jsonify({"answer": answer, "tts": answer})

            cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold, deal_type) VALUES (?, ?, ?)",
                           (user_id, threshold, deal_type))
            conn.commit()

            answer = f"Got it! I’ll notify you of new {deal_type if deal_type != 'Any' else 'deals'} over ${threshold}. 🔔 Make sure your notification settings are enabled!"
            log_user_activity(user_id, "set_deal_alert", {"threshold": threshold, "deal_type": deal_type}, cursor, conn)
            return jsonify({"answer": answer, "tts": answer})

        else:
            answer = "I’m not sure what you mean! 😅 Try something like 'send realblast', 'predict deal', or 'sync contacts'. What do you want to do?"
            return jsonify({"answer": answer, "tts": answer})
