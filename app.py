import os
import json
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pytesseract
from PIL import Image
from geopy.geocoders import Nominatim
import exifread
import pandas as pd
import PyPDF2
import requests
from typing import Optional
import io
from fuzzywuzzy import fuzz
from urllib.parse import quote

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load knowledge base
with open("knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

# xAI API configuration
XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_API_URL = "https://api.x.ai/v1/chat/completions"

# RealNex API configuration (V1)
REALNEX_API_URL = "https://sync.realnex.com"

# Geocoder
geolocator = Nominatim(user_agent="realnex_chatbot")

class ChatRequest(BaseModel):
    message: str
    personality: str
    token: Optional[str] = None

class UploadResponse:
    def __init__(self, response: str, snapshot: Optional[str] = None):
        self.response = response
        self.snapshot = snapshot

def call_xai_api(prompt: str, personality: str) -> str:
    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "You are Maverick, a knowledgeable assistant answering questions about RealNex based on the provided knowledge base. Use the knowledge base first, then provide general insights if needed."
        if personality == "maverick"
        else "You are Goose, a data processing assistant that handles file uploads, extracts data, and prepares it for import into RealNex CRM."
    )
    data = {
        "model": "grok-3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }
    response = requests.post(XAI_API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def extract_geocoordinates(image: bytes) -> Optional[tuple]:
    tags = exifread.process_file(io.BytesIO(image))
    lat = tags.get("GPS GPSLatitude")
    lon = tags.get("GPS GPSLongitude")
    if lat and lon:
        lat = float(lat.values[0] + lat.values[1]/60 + lat.values[2]/3600)
        lon = float(lon.values[0] + lon.values[1]/60 + lon.values[2]/3600)
        return lat, lon
    return None

def geocode_to_address(lat: float, lon: float) -> str:
    location = geolocator.reverse((lat, lon), language="en")
    return location.address if location else "Address not found"

def extract_text_from_image(image: Image.Image) -> str:
    return pytesseract.image_to_string(image)

def extract_text_from_pdf(file: bytes) -> str:
    pdf = PyPDF2.PdfReader(io.BytesIO(file))
    text = ""
    for page in pdf.pages:
        text += page.extract_text() or ""
    return text

def parse_spreadsheet(file: bytes, filename: str) -> pd.DataFrame:
    if filename.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(file))
    return pd.read_csv(io.BytesIO(file))

def get_crm_field_definitions(table_name: str, token: str) -> list:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.get(
        f"{REALNEX_API_URL}/api/v1/Crm/definitions/{table_name}",
        headers=headers
    )
    response.raise_for_status()
    return response.json()

def auto_match_fields(data: dict, table_name: str, token: str) -> dict:
    fields = get_crm_field_definitions(table_name, token)
    matched = {}
    for key, value in data.items():
        key_lower = key.lower()
        best_score = 0
        best_field = None
        for field in fields:
            field_name = field.get("name", "").lower()
            score = fuzz.token_sort_ratio(key_lower, field_name)
            if score > best_score and score > 80:
                best_score = score
                best_field = field_name
        if best_field:
            matched[best_field] = value
    return matched

@app.post("/chat")
async def chat(request: ChatRequest):
    if request.personality == "maverick":
        for item in knowledge_base:
            if request.message.lower() in item["question"].lower():
                prompt = f"Question: {request.message}\nAnswer: {item['answer']}"
                response = call_xai_api(prompt, request.personality)
                return {"response": response}
        response = call_xai_api(
            f"Question: {request.message}\nNo specific answer found in knowledge base. Provide a general response about RealNex.",
            request.personality
        )
        return {"response": response}
    else:
        if not request.token:
            return {"response": "Goose: Please provide your RealNex CRM token to process data."}
        return {"response": "Goose: Please upload a file to process (image, PDF, or spreadsheet)."}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), personality: str = "goose", token: str = None):
    if personality != "goose":
        raise HTTPException(status_code=400, detail="File uploads are only supported for Goose personality.")

    if not token:
        raise HTTPException(status_code=400, detail="RealNex CRM token is required to process data.")

    file_content = await file.read()
    filename = file.filename
    response_text = ""
    snapshot = []

    if file.content_type.startswith("image"):
        image = Image.open(io.BytesIO(file_content))
        text = extract_text_from_image(image)
        company_name = text.split("\n")[0] or "Unknown Company"
        geocoordinates = extract_geocoordinates(file_content)
        extracted_data = {"name": company_name}
        
        if geocoordinates:
            address = geocode_to_address(*geocoordinates)
            address_parts = address.split(", ")
            extracted_data.update({
                "addressStreet": address_parts[0],
                "city": address_parts[1] if len(address_parts) > 1 else "",
                "state": address_parts[2] if len(address_parts) > 2 else "",
                "zip": address_parts[3] if len(address_parts) > 3 else "",
                "country": "US"
            })
            
            matched_fields = auto_match_fields(extracted_data, "Principal", token)
            response_text = (
                f"Extracted: Company Name: {company_name}\n"
                f"Geocoordinates: {geocoordinates}\n"
                f"Address: {address}\n\n"
                f"Mapped to RealNex CRM Fields (Principal):\n"
                + "\n".join([f"- {k}: {v}" for k, v in matched_fields.items()])
                + "\n\nSince direct CRM integration is not available with the V1 API, please copy this data into a CSV file and import it into RealNex CRM manually."
            )
            snapshot.append("Image Data:")
            snapshot.append(f"- Extracted Text: {text}")
            snapshot.append(f"- Geocoordinates: {geocoordinates}")
            snapshot.append(f"- Address: {address}")
            snapshot.append("- Mapped Fields:")
            for k, v in matched_fields.items():
                snapshot.append(f"  - {k}: {v}")
        else:
            matched_fields = auto_match_fields(extracted_data, "Principal", token)
            response_text = (
                f"Extracted: Company Name: {company_name}\n"
                f"No geocoordinates found.\n\n"
                f"Mapped to RealNex CRM Fields (Principal):\n"
                + "\n".join([f"- {k}: {v}" for k, v in matched_fields.items()])
                + "\n\nSince direct CRM integration is not available with the V1 API, please copy this data into a CSV file and import it into RealNex CRM manually."
            )
            snapshot.append("Image Data:")
            snapshot.append(f"- Extracted Text: {text}")
            snapshot.append(f"- Geocoordinates: None")
            snapshot.append("- Mapped Fields:")
            for k, v in matched_fields.items():
                snapshot.append(f"  - {k}: {v}")

    elif file.content_type == "application/pdf":
        text = extract_text_from_pdf(file_content)
        company_name = text.split("\n")[0] or "Unknown Company"
        extracted_data = {"name": company_name}
        matched_fields = auto_match_fields(extracted_data, "Principal", token)
        response_text = (
            f"Extracted PDF: {text[:100]}...\n\n"
            f"Mapped to RealNex CRM Fields (Principal):\n"
            + "\n".join([f"- {k}: {v}" for k, v in matched_fields.items()])
            + "\n\nSince direct CRM integration is not available with the V1 API, please copy this data into a CSV file and import it into RealNex CRM manually."
        )
        snapshot.append("PDF Data:")
        snapshot.append(f"- Extracted Text: {text[:100]}...")
        snapshot.append("- Mapped Fields:")
        for k, v in matched_fields.items():
            snapshot.append(f"  - {k}: {v}")

    elif file.content_type in ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
        df = parse_spreadsheet(file_content, filename)
        matched_fields = {}
        for col in df.columns:
            col_lower = col.lower()
            best_score = 0
            best_field = None
            fields = get_crm_field_definitions("Principal", token)
            for field in fields:
                field_name = field.get("name", "").lower()
                score = fuzz.token_sort_ratio(col_lower, field_name)
                if score > best_score and score > 80:
                    best_score = score
                    best_field = field_name
            if best_field:
                matched_fields[best_field] = col

        response_text = (
            f"Spreadsheet processed. Matched fields:\n"
            + "\n".join([f"- {k}: {v}" for k, v in matched_fields.items()])
            + f"\n\nProcessed {len(df)} rows.\n"
            + "Since direct CRM integration is not available with the V1 API, please export this data to a CSV file with the matched fields and import it into RealNex CRM manually."
        )
        snapshot.append("Spreadsheet Data:")
        snapshot.append(f"- Matched Fields: {matched_fields}")
        snapshot.append(f"- Processed Rows: {len(df)}")

    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    snapshot_text = "\n".join(snapshot)
    return {"response": call_xai_api(response_text, personality), "snapshot": snapshot_text}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
