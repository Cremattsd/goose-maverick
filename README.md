# Goose & Maverick - README

## Overview
This Flask-based app provides an interactive UI for:
- Uploading and parsing business cards, PDFs, photos, and Excel files
- Importing contact, company, space, and comp data into RealNex CRM
- Chatting with Maverick, your AI assistant for CRE, RealNex, Pix-Virtual, and ViewLabs
- Syncing contacts to Mailchimp or Constant Contact

## Features
- 🧠 **AI Assistant (Maverick):** Ask questions about RealNex, VR tools, and usage guidance.
- 📸 **Goose OCR Importer:** Drag and drop cards, PDFs, and spreadsheets for CRM sync.
- 🔐 **Token Validation:** Ensures valid RealNex Bearer tokens before uploads.
- 📬 **Email Marketing Sync:** Sync contact data to RealNex, Mailchimp, or Constant Contact.
- ⚖️ **Legal Consent:** Users must agree to RealNex Terms before uploading data.

## Environment Variables
```env
# OpenAI API
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# RealNex API
REALNEX_API_BASE=https://sync.realnex.com/api/v1

# Mailchimp (Optional)
MAILCHIMP_API_KEY=...
MAILCHIMP_LIST_ID=...
MAILCHIMP_SERVER_PREFIX=usX

# Constant Contact (Optional)
CONSTANT_CONTACT_API_KEY=...
CONSTANT_CONTACT_ACCESS_TOKEN=...
CONSTANT_CONTACT_LIST_ID=...

# Campaign Sync Defaults
DEFAULT_CAMPAIGN_MODE=realnex  # Options: realnex, mailchimp, constant_contact
UNLOCK_EMAIL_PROVIDER_SELECTION=false
```

## Endpoints
### `/`
Serves the frontend UI (chat + upload).

### `/ask` (POST)
Send a message to Maverick. Returns a chat reply.

### `/validate-token` (POST)
Validate RealNex bearer token.

### `/upload-business-card` (POST)
Upload a photo or PDF of a business card and import to CRM.

### `/suggest-mapping` (POST)
Upload an Excel file and receive suggested column mappings.

### `/bulk-import` (POST)
Submit an Excel file + mapping JSON to import multiple contacts.

### `/download-listing-template` (GET)
Download the official RealNex listing upload Excel template.

### `/get-listing-instructions` (GET)
Get instructions for uploading listings.

### `/sync-to-mailchimp` (POST)
Send a contact to Mailchimp if enabled.

### `/sync-to-constant-contact` (POST)
Send a contact to Constant Contact if enabled.

### `/terms` (GET)
Returns the RealNex legal agreement string required before importing data.

## Permissions
All RealNex data imports and lookups respect CRM permissions tied to the user's token.

## File Structure
```bash
project-root/
├── app.py
├── goose_parser_tools.py
├── static/
│   └── index.html (chat UI)
├── upload/ (temporary file uploads)
└── README.md
```

## Deployment
Use [Render](https://render.com/) or another platform to run `gunicorn app:app -b 0.0.0.0:$PORT`

---

🛡 By using this tool, you confirm agreement to the RealNex [Terms of Use](https://realnex.com/Terms).

🚀 Enjoy the upload party with Goose + Maverick!
