import re
import logging
import httpx
from utils import get_user_settings, get_token, log_user_activity, log_duplicate

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
    """Handle syncing data with RealNex, Mailchimp, Constant Contact, Apollo.io, Seamless.AI, and ZoomInfo."""
    match = re.match(r'sync (crm|contacts|deals|all)', query, re.IGNORECASE)
    if not match:
        return "Invalid sync command. Use: 'sync [crm|contacts|deals|all]'"

    sync_type = match.group(1).lower()
    settings = get_user_settings(user_id, cursor, conn)

    # Fetch contacts from the database (populated via OCR or manual entry)
    cursor.execute("SELECT id, name, email FROM contacts WHERE user_id = ?", (user_id,))
    existing_contacts = cursor.fetchall()
    existing_contacts_list = [{"id": c[0], "name": c[1], "email": c[2]} for c in existing_contacts]

    # Initialize list to hold all contacts to sync to RealNex
    contacts_to_sync = existing_contacts_list.copy()

    # Fetch contacts from Apollo.io
    apollo_token = get_token(user_id, "apollo", cursor)
    apollo_group_id = settings.get("apollo_group_id")
    if apollo_token and apollo_group_id:
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"https://api.apollo.io/v1/lists/{apollo_group_id}/contacts",
                    headers={'Authorization': f'Bearer {apollo_token}'}
                )
                response.raise_for_status()
                apollo_contacts = response.json().get('contacts', [])
                for contact in apollo_contacts:
                    contact_id = f"apollo_{contact['id']}_{user_id}"
                    contact_data = {"id": contact_id, "name": contact.get('name', ''), "email": contact.get('email', '')}
                    contacts_to_sync.append(contact_data)
                    # Add to database if not already present
                    cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                   (contact_id, contact_data['name'], contact_data['email'], user_id))
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to fetch contacts from Apollo.io: {e}")

    # Fetch contacts from Seamless.AI
    seamless_token = get_token(user_id, "seamless", cursor)
    seamless_group_id = settings.get("seamless_group_id")
    if seamless_token and seamless_group_id:
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"https://api.seamless.ai/v1/lists/{seamless_group_id}/contacts",
                    headers={'Authorization': f'Bearer {seamless_token}'}
                )
                response.raise_for_status()
                seamless_contacts = response.json().get('contacts', [])
                for contact in seamless_contacts:
                    contact_id = f"seamless_{contact['id']}_{user_id}"
                    contact_data = {"id": contact_id, "name": contact.get('name', ''), "email": contact.get('email', '')}
                    contacts_to_sync.append(contact_data)
                    # Add to database if not already present
                    cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                   (contact_id, contact_data['name'], contact_data['email'], user_id))
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to fetch contacts from Seamless.AI: {e}")

    # Fetch contacts from ZoomInfo
    zoominfo_token = get_token(user_id, "zoominfo", cursor)
    zoominfo_group_id = settings.get("zoominfo_group_id")
    if zoominfo_token and zoominfo_group_id:
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"https://api.zoominfo.com/v1/lists/{zoominfo_group_id}/contacts",
                    headers={'Authorization': f'Bearer {zoominfo_token}'}
                )
                response.raise_for_status()
                zoominfo_contacts = response.json().get('contacts', [])
                for contact in zoominfo_contacts:
                    contact_id = f"zoominfo_{contact['id']}_{user_id}"
                    contact_data = {"id": contact_id, "name": contact.get('name', ''), "email": contact.get('email', '')}
                    contacts_to_sync.append(contact_data)
                    # Add to database if not already present
                    cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, user_id) VALUES (?, ?, ?, ?)",
                                   (contact_id, contact_data['name'], contact_data['email'], user_id))
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to fetch contacts from ZoomInfo: {e}")

    if not contacts_to_sync:
        return "No contacts found to sync."

    # Sync with RealNex
    realnex_token = get_token(user_id, "realnex", cursor)
    realnex_group_id = settings.get("realnex_group_id")
    if not realnex_token:
        return "No RealNex token found. Please set it in settings."
    if not realnex_group_id:
        return "No RealNex group selected for syncing. Please select a group in settings."

    try:
        with httpx.Client() as client:
            # Sync contacts to RealNex in the selected group
            for contact in contacts_to_sync:
                response = client.post(
                    "https://api.realnex.com/v1/contacts",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    json={
                        "name": contact["name"],
                        "email": contact["email"],
                        "source": "CRE Chat Bot",
                        "group_id": realnex_group_id
                    }
                )
                response.raise_for_status()
                log_user_activity(user_id, "sync_realnex_contact", {"contact_id": contact["id"], "group_id": realnex_group_id}, cursor, conn)
    except Exception as e:
        logger.error(f"Failed to sync with RealNex: {e}")
        return f"Failed to sync with RealNex: {str(e)}"

    # Sync with Mailchimp
    mailchimp_api_key = get_token(user_id, "mailchimp", cursor)
    mailchimp_group_id = settings.get("mailchimp_group_id")
    if mailchimp_api_key and mailchimp_group_id:
        try:
            with httpx.Client() as client:
                for contact in contacts_to_sync:
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
    constant_contact_group_id = settings.get("constant_contact_group_id")
    if constant_contact_token and constant_contact_group_id:
        try:
            with httpx.Client() as client:
                for contact in contacts_to_sync:
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
