from flask import jsonify
from config import *
from database import conn, cursor
from utils import log_user_activity

def handle_draft_email(message, user_id, settings, openai_client):
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

    return None
