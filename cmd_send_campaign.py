from flask import jsonify
from email.mime.text import MIMEText
import smtplib
import httpx
from mailchimp_marketing import Client as MailchimpClient

from config import *
from database import conn, cursor
from utils import *

def handle_send_campaign(message, user_id, data, points, email_credits, has_msa, settings, socketio, twilio_client):
    if 'send realblast' in message:
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

    return None
