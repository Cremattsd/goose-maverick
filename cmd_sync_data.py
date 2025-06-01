import re
import logging
import httpx
from .utils import get_user_settings, get_token, log_user_activity, log_duplicate

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

def handle_sync_data(query, user_id, cursor, conn):
    """Handle syncing data with RealNex, Mailchimp, and Constant Contact."""
    match = re.match(r'sync (crm|contacts|deals|all)', query, re.IGNORECASE)
    if not match:
        return "Invalid sync command. Use: 'sync [crm|contacts|deals|all]'"

    sync_type = match.group(1).lower()
    settings = get_user_settings(user_id, cursor, conn)
    
    # Fetch contacts from the database (populated via OCR or manual entry)
    cursor.execute("SELECT id, name, email FROM contacts WHERE user_id = ?", (user_id,))
    contacts = cursor.fetchall()
    contacts_list = [{"id": c[0], "name": c[1], "email": c[2]} for c in contacts]

    if not contacts_list:
        return "No contacts found to sync."

    # Sync with RealNex
    realnex_token = get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return "No RealNex token found. Please set it in settings."

    try:
        with httpx.Client() as client:
            # Sync contacts to RealNex
            for contact in contacts_list:
                response = client.post(
                    "https://api.realnex.com/v1/contacts",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    json={
                        "name": contact["name"],
                        "email": contact["email"],
                        "source": "CRE Chat Bot"
                    }
                )
                response.raise_for_status()
                log_user_activity(user_id, "sync_realnex_contact", {"contact_id": contact["id"]}, cursor, conn)
    except Exception as e:
        logger.error(f"Failed to sync with RealNex: {e}")
        return f"Failed to sync with RealNex: {str(e)}"

    # Sync with Mailchimp
    mailchimp_api_key = get_token(user_id, "mailchimp", cursor)
    mailchimp_group_id = settings.get("mailchimp_group_id")  # Assume this is stored in settings
    if mailchimp_api_key and mailchimp_group_id:
        try:
            with httpx.Client() as client:
                for contact in contacts_list:
                    response = client.post(
                        f"https://us1.api.mailchimp.com/3.0/lists/{mailchimp_group_id}/members",
                        auth=("anystring", mailchimp_api_key),
                        json={
                            "email_address": contact["email"],
                            "status": "subscribed",
                            "merge_fields": {"FNAME": contact["name"].split()[0] if contact["name"] else ""}
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_mailchimp_contact", {"contact_id": contact["id"]}, cursor, conn)
        except Exception as e:
            logger.error(f"Failed to sync with Mailchimp: {e}")
            return f"Failed to sync with Mailchimp: {str(e)}"

    # Sync with Constant Contact
    constant_contact_token = get_token(user_id, "constant_contact", cursor)
    constant_contact_group_id = settings.get("constant_contact_group_id")  # Assume this is stored in settings
    if constant_contact_token and constant_contact_group_id:
        try:
            with httpx.Client() as client:
                for contact in contacts_list:
                    response = client.post(
                        "https://api.cc.email/v3/contacts",
                        headers={'Authorization': f'Bearer {constant_contact_token}'},
                        json={
                            "email_address": {"address": contact["email"], "permission_to_send": "implicit"},
                            "first_name": contact["name"].split()[0] if contact["name"] else "",
                            "list_memberships": [constant_contact_group_id]
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_constant_contact_contact", {"contact_id": contact["id"]}, cursor, conn)
        except Exception as e:
            logger.error(f"Failed to sync with Constant Contact: {e}")
            return f"Failed to sync with Constant Contact: {str(e)}"

    return "Sync completed successfully!"
