from flask import jsonify
import httpx
import pandas as pd
from io import StringIO

from config import REALNEX_API_BASE
from database import conn, cursor
from utils import *

def handle_sync_data(message, user_id, data):
    if 'sync crm data' in message:
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
        return jsonify({"answer": answer, "tts": answer})

    return None
