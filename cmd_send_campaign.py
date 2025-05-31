import json
import re
import smtplib
from email.mime.text import MIMEText
import logging
from twilio.rest import Client as TwilioClient
import mailchimp_marketing as Mailchimp
import httpx
from .utils import get_user_settings, get_token, send_2fa_code, check_2fa, log_user_activity, award_points

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("chatbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def handle_send_campaign(query, user_id, cursor, conn, twilio_client, mailchimp_client):
    """Handle sending a campaign (RealBlast or Mailchimp) based on the query."""
    settings = get_user_settings(user_id, cursor, conn)
    if not settings["email_notifications"]:
        return "Email notifications are disabled in your settings."

    # Extract group and content from the query
    match = re.match(r'send (realblast|mailchimp) to group (\S+)(?: with content (.*))?', query, re.IGNORECASE)
    if not match:
        return "Invalid command format. Use: 'send [realblast|mailchimp] to group <group_id> with content <message>'"

    campaign_type, group_id, content = match.groups()
    content = content or "Check out this amazing property!"

    # Send 2FA code for verification
    if not send_2fa_code(user_id, twilio_client, cursor, conn):
        return "Failed to send 2FA code. Please try again later."

    # For simplicity, assume 2FA code is received (in production, prompt user)
    # Here we'll mock a 2FA check
    mock_2fa_code = "123456"  # Replace with actual user input in production
    if not check_2fa(user_id, mock_2fa_code, cursor, conn):
        return "2FA verification failed."

    # Proceed with sending the campaign
    if campaign_type.lower() == "realblast":
        # Send RealBlast via Twilio
        if not twilio_client:
            return "Twilio client not initialized."
        try:
            twilio_client.messages.create(
                body=content,
                from_='+1234567890',  # Replace with actual Twilio number
                to=f"+{group_id}"     # Simplified; in reality, resolve group_id to phone numbers
            )
            log_user_activity(user_id, "send_realblast", {"group_id": group_id, "content": content}, cursor, conn)
            _, _, _, points_message = award_points(user_id, 10, "sending RealBlast", cursor, conn)
            return f"RealBlast sent to group {group_id}! {points_message}"
        except Exception as e:
            logger.error(f"Failed to send RealBlast: {e}")
            return f"Failed to send RealBlast: {str(e)}"

    elif campaign_type.lower() == "mailchimp":
        # Send Mailchimp campaign
        if not mailchimp_client:
            return "Mailchimp client not initialized."
        try:
            # Get Mailchimp API key
            api_key = get_token(user_id, "mailchimp", cursor)
            if not api_key:
                return "No Mailchimp API key found. Please authenticate."

            # Configure Mailchimp client
            mailchimp_client.set_config({"api_key": api_key, "server": "us1"})

            # Create a campaign
            with httpx.Client() as client:
                response = client.post(
                    f"https://us1.api.mailchimp.com/3.0/campaigns",
                    auth=("anystring", api_key),
                    json={
                        "type": "regular",
                        "recipients": {"list_id": group_id},
                        "settings": {
                            "subject_line": "New Property Alert",
                            "from_name": "CRE Bot",
                            "reply_to": "noreply@crebot.com"
                        }
                    }
                )
                response.raise_for_status()
                campaign = response.json()

            # Set campaign content
            with httpx.Client() as client:
                response = client.put(
                    f"https://us1.api.mailchimp.com/3.0/campaigns/{campaign['id']}/content",
                    auth=("anystring", api_key),
                    json={"plain_text": content}
                )
                response.raise_for_status()

            # Send the campaign
            with httpx.Client() as client:
                response = client.post(
                    f"https://us1.api.mailchimp.com/3.0/campaigns/{campaign['id']}/actions/send",
                    auth=("anystring", api_key)
                )
                response.raise_for_status()

            log_user_activity(user_id, "send_mailchimp", {"group_id": group_id, "content": content}, cursor, conn)
            _, _, _, points_message = award_points(user_id, 10, "sending Mailchimp campaign", cursor, conn)
            return f"Mailchimp campaign sent to group {group_id}! {points_message}"
        except Exception as e:
            logger.error(f"Failed to send Mailchimp campaign: {e}")
            return f"Failed to send Mailchimp campaign: {str(e)}"

    return "Unsupported campaign type."
