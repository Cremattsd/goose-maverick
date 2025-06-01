import re
import logging
import httpx
from datetime import datetime
from .utils import get_user_settings, get_token, log_user_activity, hash_entity, log_duplicate, log_health_history

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

def check_email_health(email):
    """Check email health using MailboxValidator API (simplified for demo)."""
    api_key = "your_mailboxvalidator_api_key"  # Replace with your API key
    try:
        with httpx.Client() as client:
            response = client.get(
                "https://api.mailboxvalidator.com/v1/email/validation/single",
                params={"email": email, "key": api_key}
            )
            response.raise_for_status()
            result = response.json()
            # Simplified scoring: 100 if valid, 50 if risky, 0 if invalid
            if result.get("is_verified", False):
                return 100
            elif result.get("is_high_risk", False):
                return 50
            else:
                return 0
    except Exception as e:
        logger.error(f"Failed to check email health for {email}: {e}")
        return 0

def check_phone_health(phone):
    """Check phone health using NumVerify API (simplified for demo)."""
    api_key = "your_numverify_api_key"  # Replace with your API key
    try:
        with httpx.Client() as client:
            response = client.get(
                "http://apilayer.net/api/validate",
                params={"access_key": api_key, "number": phone, "country_code": "", "format": 1}
            )
            response.raise_for_status()
            result = response.json()
            # Simplified scoring: 100 if valid, 0 if invalid
            return 100 if result.get("valid", False) else 0
    except Exception as e:
        logger.error(f"Failed to check phone health for {phone}: {e}")
        return 0

def handle_sync_data(query, user_id, cursor, conn):
    """Handle syncing data with RealNex, Mailchimp, Constant Contact, Apollo.io, Seamless.AI, and ZoomInfo."""
    match = re.match(r'sync (crm|contacts|companies|properties|spaces|all)', query, re.IGNORECASE)
    if not match:
        return "Invalid sync command. Use: 'sync [crm|contacts|companies|properties|spaces|all]'"

    sync_type = match.group(1).lower()
    settings = get_user_settings(user_id, cursor, conn)
    realnex_token = get_token(user_id, "realnex", cursor)
    realnex_group_id = settings.get("realnex_group_id")

    if not realnex_token:
        return "No RealNex token found. Please set it in settings."
    if not realnex_group_id:
        return "No RealNex group selected for syncing. Please select a group in settings."

    # Define entities to sync based on command
    entities_to_sync = []
    if sync_type in ["crm", "all"]:
        entities_to_sync.extend(["contacts", "companies", "properties", "spaces"])
    else:
        entities_to_sync.append(sync_type)

    # Initialize lists for all entities
    all_contacts = []
    all_companies = []
    all_properties = []
    all_spaces = []

    # Fetch local entities from database
    if "contacts" in entities_to_sync:
        cursor.execute("SELECT id, name, email, phone FROM contacts WHERE user_id = ?", (user_id,))
        local_contacts = [{"id": c[0], "name": c[1], "email": c[2], "phone": c[3] or ""} for c in cursor.fetchall()]
        for contact in local_contacts:
            contact_hash = hash_entity(contact, "contact")
            cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, contact_hash))
            if not cursor.fetchone():
                # Check email and phone health
                email_score = check_email_health(contact["email"]) if contact["email"] else 0
                phone_score = check_phone_health(contact["phone"]) if contact["phone"] else 0
                log_health_history(user_id, contact["id"], email_score, phone_score, cursor, conn)
                all_contacts.append(contact)
            else:
                log_duplicate(user_id, contact, "contact", cursor, conn)

    # Fetch companies, properties, spaces from RealNex (simplified for demo)
    if "companies" in entities_to_sync:
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/companies",
                    headers={'Authorization': f'Bearer {realnex_token}'}
                )
                response.raise_for_status()
                companies = response.json()
                for company in companies:
                    company_data = {"id": company["id"], "name": company.get("name", ""), "address": company.get("address", "")}
                    company_hash = hash_entity(company_data, "company")
                    cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, company_hash))
                    if not cursor.fetchone():
                        all_companies.append(company_data)
                    else:
                        log_duplicate(user_id, company_data, "company", cursor, conn)
        except Exception as e:
            logger.error(f"Failed to fetch companies from RealNex: {e}")

    if "properties" in entities_to_sync:
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/properties",
                    headers={'Authorization': f'Bearer {realnex_token}'}
                )
                response.raise_for_status()
                properties = response.json()
                for prop in properties:
                    prop_data = {"id": prop["id"], "address": prop.get("address", ""), "city": prop.get("city", ""), "zip": prop.get("zip", "")}
                    prop_hash = hash_entity(prop_data, "property")
                    cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, prop_hash))
                    if not cursor.fetchone():
                        all_properties.append(prop_data)
                    else:
                        log_duplicate(user_id, prop_data, "property", cursor, conn)
        except Exception as e:
            logger.error(f"Failed to fetch properties from RealNex: {e}")

    if "spaces" in entities_to_sync:
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/spaces",
                    headers={'Authorization': f'Bearer {realnex_token}'}
                )
                response.raise_for_status()
                spaces = response.json()
                for space in spaces:
                    space_data = {"id": space["id"], "property_id": space.get("property_id", ""), "space_number": space.get("space_number", "")}
                    space_hash = hash_entity(space_data, "space")
                    cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, space_hash))
                    if not cursor.fetchone():
                        all_spaces.append(space_data)
                    else:
                        log_duplicate(user_id, space_data, "space", cursor, conn)
        except Exception as e:
            logger.error(f"Failed to fetch spaces from RealNex: {e}")

    # Fetch contacts, companies, properties, spaces from Apollo.io, Seamless.AI, ZoomInfo
    apollo_token = get_token(user_id, "apollo", cursor)
    apollo_group_id = settings.get("apollo_group_id")
    if apollo_token and apollo_group_id:
        try:
            with httpx.Client() as client:
                if "contacts" in entities_to_sync:
                    response = client.get(
                        f"https://api.apollo.io/v1/lists/{apollo_group_id}/contacts",
                        headers={'Authorization': f'Bearer {apollo_token}'}
                    )
                    response.raise_for_status()
                    apollo_contacts = response.json().get('contacts', [])
                    for contact in apollo_contacts:
                        contact_id = f"apollo_{contact['id']}_{user_id}"
                        contact_data = {
                            "id": contact_id,
                            "name": contact.get('name', ''),
                            "email": contact.get('email', ''),
                            "phone": contact.get('phone', '')
                        }
                        contact_hash = hash_entity(contact_data, "contact")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, contact_hash))
                        if not cursor.fetchone():
                            email_score = check_email_health(contact_data["email"]) if contact_data["email"] else 0
                            phone_score = check_phone_health(contact_data["phone"]) if contact_data["phone"] else 0
                            log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                            all_contacts.append(contact_data)
                            cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                           (contact_id, contact_data['name'], contact_data['email'], contact_data['phone'], user_id))
                            conn.commit()
                        else:
                            log_duplicate(user_id, contact_data, "contact", cursor, conn)

                if "companies" in entities_to_sync:
                    response = client.get(
                        f"https://api.apollo.io/v1/lists/{apollo_group_id}/companies",
                        headers={'Authorization': f'Bearer {apollo_token}'}
                    )
                    response.raise_for_status()
                    apollo_companies = response.json().get('companies', [])
                    for company in apollo_companies:
                        company_id = f"apollo_company_{company['id']}_{user_id}"
                        company_data = {"id": company_id, "name": company.get('name', ''), "address": company.get('address', '')}
                        company_hash = hash_entity(company_data, "company")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, company_hash))
                        if not cursor.fetchone():
                            all_companies.append(company_data)
                        else:
                            log_duplicate(user_id, company_data, "company", cursor, conn)

                # Add properties and spaces fetching if supported by API
        except Exception as e:
            logger.error(f"Failed to fetch data from Apollo.io: {e}")

    seamless_token = get_token(user_id, "seamless", cursor)
    seamless_group_id = settings.get("seamless_group_id")
    if seamless_token and seamless_group_id:
        try:
            with httpx.Client() as client:
                if "contacts" in entities_to_sync:
                    response = client.get(
                        f"https://api.seamless.ai/v1/lists/{seamless_group_id}/contacts",
                        headers={'Authorization': f'Bearer {seamless_token}'}
                    )
                    response.raise_for_status()
                    seamless_contacts = response.json().get('contacts', [])
                    for contact in seamless_contacts:
                        contact_id = f"seamless_{contact['id']}_{user_id}"
                        contact_data = {
                            "id": contact_id,
                            "name": contact.get('name', ''),
                            "email": contact.get('email', ''),
                            "phone": contact.get('phone', '')
                        }
                        contact_hash = hash_entity(contact_data, "contact")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, contact_hash))
                        if not cursor.fetchone():
                            email_score = check_email_health(contact_data["email"]) if contact_data["email"] else 0
                            phone_score = check_phone_health(contact_data["phone"]) if contact_data["phone"] else 0
                            log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                            all_contacts.append(contact_data)
                            cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                           (contact_id, contact_data['name'], contact_data['email'], contact_data['phone'], user_id))
                            conn.commit()
                        else:
                            log_duplicate(user_id, contact_data, "contact", cursor, conn)
        except Exception as e:
            logger.error(f"Failed to fetch data from Seamless.AI: {e}")

    zoominfo_token = get_token(user_id, "zoominfo", cursor)
    zoominfo_group_id = settings.get("zoominfo_group_id")
    if zoominfo_token and zoominfo_group_id:
        try:
            with httpx.Client() as client:
                if "contacts" in entities_to_sync:
                    response = client.get(
                        f"https://api.zoominfo.com/v1/lists/{zoominfo_group_id}/contacts",
                        headers={'Authorization': f'Bearer {zoominfo_token}'}
                    )
                    response.raise_for_status()
                    zoominfo_contacts = response.json().get('contacts', [])
                    for contact in zoominfo_contacts:
                        contact_id = f"zoominfo_{contact['id']}_{user_id}"
                        contact_data = {
                            "id": contact_id,
                            "name": contact.get('name', ''),
                            "email": contact.get('email', ''),
                            "phone": contact.get('phone', '')
                        }
                        contact_hash = hash_entity(contact_data, "contact")
                        cursor.execute("SELECT contact_hash FROM duplicates_log WHERE user_id = ? AND contact_hash = ?", (user_id, contact_hash))
                        if not cursor.fetchone():
                            email_score = check_email_health(contact_data["email"]) if contact_data["email"] else 0
                            phone_score = check_phone_health(contact_data["phone"]) if contact_data["phone"] else 0
                            log_health_history(user_id, contact_id, email_score, phone_score, cursor, conn)
                            all_contacts.append(contact_data)
                            cursor.execute("INSERT OR IGNORE INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                                           (contact_id, contact_data['name'], contact_data['email'], contact_data['phone'], user_id))
                            conn.commit()
                        else:
                            log_duplicate(user_id, contact_data, "contact", cursor, conn)
        except Exception as e:
            logger.error(f"Failed to fetch data from ZoomInfo: {e}")

    # Sync to RealNex
    try:
        with httpx.Client() as client:
            if all_contacts:
                for contact in all_contacts:
                    response = client.post(
                        "https://api.realnex.com/v1/contacts",
                        headers={'Authorization': f'Bearer {realnex_token}'},
                        json={
                            "name": contact["name"],
                            "email": contact["email"],
                            "phone": contact["phone"],
                            "source": "CRE Chat Bot",
                            "group_id": realnex_group_id
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_realnex_contact", {"contact_id": contact["id"], "group_id": realnex_group_id}, cursor, conn)

            if all_companies:
                for company in all_companies:
                    response = client.post(
                        "https://api.realnex.com/v1/companies",
                        headers={'Authorization': f'Bearer {realnex_token}'},
                        json={
                            "name": company["name"],
                            "address": company["address"],
                            "source": "CRE Chat Bot",
                            "group_id": realnex_group_id
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_realnex_company", {"company_id": company["id"], "group_id": realnex_group_id}, cursor, conn)

            if all_properties:
                for prop in all_properties:
                    response = client.post(
                        "https://api.realnex.com/v1/properties",
                        headers={'Authorization': f'Bearer {realnex_token}'},
                        json={
                            "address": prop["address"],
                            "city": prop["city"],
                            "zip": prop["zip"],
                            "source": "CRE Chat Bot",
                            "group_id": realnex_group_id
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_realnex_property", {"property_id": prop["id"], "group_id": realnex_group_id}, cursor, conn)

            if all_spaces:
                for space in all_spaces:
                    response = client.post(
                        "https://api.realnex.com/v1/spaces",
                        headers={'Authorization': f'Bearer {realnex_token}'},
                        json={
                            "property_id": space["property_id"],
                            "space_number": space["space_number"],
                            "source": "CRE Chat Bot",
                            "group_id": realnex_group_id
                        }
                    )
                    response.raise_for_status()
                    log_user_activity(user_id, "sync_realnex_space", {"space_id": space["id"], "group_id": realnex_group_id}, cursor, conn)

    except Exception as e:
        logger.error(f"Failed to sync with RealNex: {e}")
        return f"Failed to sync with RealNex: {str(e)}"

    # Sync contacts to Mailchimp
    mailchimp_api_key = get_token(user_id, "mailchimp", cursor)
    mailchimp_group_id = settings.get("mailchimp_group_id")
    if mailchimp_api_key and mailchimp_group_id and all_contacts:
        try:
            with httpx.Client() as client:
                for contact in all_contacts:
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

    # Sync contacts to Constant Contact
    constant_contact_token = get_token(user_id, "constant_contact", cursor)
    constant_contact_group_id = settings.get("constant_contact_group_id")
    if constant_contact_token and constant_contact_group_id and all_contacts:
        try:
            with httpx.Client() as client:
                for contact in all_contacts:
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
