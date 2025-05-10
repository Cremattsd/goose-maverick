# 🦢 Goose Prime + 🧠 Maverick AI

## 🚀 The Ultimate RealNex Smart Importer & Assistant

This is a full-stack AI-powered tool built to:
- Scan business cards, property flyers, and spreadsheets
- Automatically extract and sync data to RealNex CRM
- Generate follow-up emails
- Sync stale contacts to Mailchimp & Constant Contact
- Answer common RealNex questions (Maverick AI)

-----

## 📁 Folder Structure

```
goose-prime/
├── app.py                     # Main Flask backend
├── goose_parser_tools.py     # Tools for PDFs, Excels, PDF log
├── knowledge_base.json       # Q&A content for Maverick AI
├── static/
│   └── index.html             # Frontend UI (Goose + Maverick)
├── uploads/                  # Temporary uploads
├── requirements.txt          # Python deps
└── README.md                 # This file
```

---

## 📦 Requirements

```
Flask
pytesseract
Pillow
exifread
geopy
requests
fitz
pandas
fpdf
gunicorn
```

---

## 🧪 Setup (Local or Render)

1. Clone the repo:
   ```bash
   git clone <your repo>
   cd goose-prime
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   python app.py
   # OR for production:
   gunicorn app:app
   ```

4. Visit: [http://localhost:5000/static/index.html](http://localhost:5000/static/index.html)

---

## 🔐 RealNex CRM Token Required

You’ll need to get your RealNex Bearer token from the RealNex Developer Console or Admin.
Paste it into the UI when prompted.

---

## 🧠 Maverick AI Knowledge Base

Update `knowledge_base.json` with any common RealNex questions + answers.
Used by the `/ask` endpoint.

---

## 🔁 Contact Sync & Grouping

- `/sync-followups` → Finds contacts with no activity in X days and adds to "Follow Up Group"
- `/sync-mailchimp` → Sends those contacts to Mailchimp (requires API key + audience ID)
- `/sync-constantcontact` → Sends to Constant Contact (requires API + list ID)

---

## 🧾 PDF Import Logs

- Every upload generates a summary log
- Use `generate_pdf_log()` in `goose_parser_tools.py` to create a printable/email-friendly PDF

---

## 📥 File Uploads Supported

| File Type | Action |
|-----------|--------|
| JPG/PNG   | OCR business card + scan + import + follow-up |
| PDF       | Parse property flyer (experimental) |
| Excel     | Bulk contact import (auto-mapping headers) |

---

## ✍️ Credits

Created by **Matty** 💼
Coded + trained by Goose 🦢 and Maverick 🧠 (with OpenAI inside)

---

## 🛡️ Final Notes

- All logic is token-based — no exposed CRM keys
- Add your own Mailchimp + Constant Contact keys as needed
- All parsing and uploads happen in-memory or `/uploads/`
- Delete old files manually if needed

---

Now go dominate the CRM game. 🦾
