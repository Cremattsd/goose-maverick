import httpx
import json
import hashlib
import sqlite3
from datetime import datetime

# Example functions
def get_user_settings(user_id, cursor, conn):
    cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
    settings = cursor.fetchone()
    if settings:
        # Convert tuple to dict based on column names
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, settings))
    return {}

def get_token(user_id, service, cursor):
    # Map service to the corresponding API key column in user_settings
    service_to_column = {
        "mailchimp": "mailchimp_api_key",
        "realnex": "realnex_api_key",
        # Add other services as needed
    }
    column = service_to_column.get(service)
    if not column:
        return None
    cursor.execute(f"SELECT {column} FROM user_settings WHERE user_id = ?", (user_id,))
    token = cursor.fetchone()
    return token[0] if token else None

def log_user_activity(user_id, action, details, cursor, conn):
    timestamp = datetime.now().isoformat()
    details_json = json.dumps(details)
    cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, action, details_json, timestamp))
    conn.commit()

def log_duplicate(user_id, contact_data, entity_type, cursor, conn):
    contact_hash = hashlib.md5(json.dumps(contact_data, sort_keys=True).encode()).hexdigest()
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO duplicates_log (user_id, contact_hash, contact_data, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, contact_hash, json.dumps(contact_data), timestamp))
    conn.commit()

def sync_to_mailchimp(user_id, contact_data, cursor, conn):
    # Fetch the user's Mailchimp API key
    api_key = get_token(user_id, "mailchimp", cursor)
    if not api_key:
        log_user_activity(user_id, "sync_to_mailchimp", {
            "contact_id": contact_data.get("id"),
            "status": "skipped",
            "reason": "No Mailchimp API key provided"
        }, cursor, conn)
        return

    try:
        # Fetch the user's Mailchimp group ID
        settings = get_user_settings(user_id, cursor, conn)
        group_id = settings.get("mailchimp_group_id", "default_list_id")
        if not group_id:
            group_id = "default_list_id"  # Fallback if not set

        # Sync to Mailchimp
        with httpx.Client() as client:
            response = client.post(
                f"https://api.mailchimp.com/3.0/lists/{group_id}/members",
                headers={'Authorization': f'Bearer {api_key}'},
                json={
                    "email_address": contact_data.get("email", ""),
                    "status": "subscribed",
                    "merge_fields": {
                        "FNAME": contact_data.get("firstName", ""),
                        "LNAME": contact_data.get("lastName", "")
                    }
                }
            )
            response.raise_for_status()
            log_user_activity(user_id, "sync_to_mailchimp", {
                "contact_id": contact_data.get("id"),
                "status": "success"
            }, cursor, conn)
    except Exception as e:
        log_user_activity(user_id, "sync_to_mailchimp", {
            "contact_id": contact_data.get("id"),
            "status": "failed",
            "error": str(e)
        }, cursor, conn)

# Other utility functions
def hash_entity(entity_data, entity_type):
    return hashlib.md5(json.dumps(entity_data, sort_keys=True).encode()).hexdigest()

def search_realnex_entities(user_id, entity_type, query_params, cursor):
    token = get_token(user_id, "realnex", cursor)
    if not token:
        return []
    try:
        with httpx.Client() as client:
            response = client.get(
                f"https://sync.realnex.com/api/v1/Crm/{entity_type}",
                headers={'Authorization': f'Bearer {token}'},
                params=query_params
            )
            response.raise_for_status()
            return response.json().get("value", [])
    except Exception:
        return []

def get_users(user_id, cursor):
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if user:
        return [{"userId": user[0], "userName": user[1]}]
    return []

def get_field_mappings(user_id, entity_type, cursor):
    # Simplified mock for field mappings
    return {
        "name": "Name:",
        "address": "Address:",
        "city": "City:",
        "zip": "Zip:",
        "space_number": "Space Number:"
    }

def sync_changes_to_realnex(user_id, cursor, conn):
    # Placeholder for syncing changes to RealNex
    pass
