import os
import json
import pytesseract
from PIL import Image
import pdf2image
import exifread
import re
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

# OCR Functions
def extract_text_from_image(image_path):
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img).strip()
    except Exception as e:
        logging.error(f"Image OCR error: {str(e)}")
        return ""

def extract_text_from_pdf(pdf_path):
    try:
        images = pdf2image.convert_from_path(pdf_path)
        return "\n".join([pytesseract.image_to_string(img) for img in images]).strip()
    except Exception as e:
        logging.error(f"PDF OCR error: {str(e)}")
        return ""

# Geo Functions
def dms_to_decimal(dms, ref):
    try:
        degrees = float(dms[0].num) / float(dms[0].den)
        minutes = float(dms[1].num) / float(dms[1].den)
        seconds = float(dms[2].num) / float(dms[2].den)
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        return -decimal if ref in ['S', 'W'] else decimal
    except Exception as e:
        logging.error(f"DMS conversion error: {str(e)}")
        return None

def extract_exif_location(image_path):
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f)
            if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                lat = tags['GPS GPSLatitude'].values
                lon = tags['GPS GPSLongitude'].values
                lat_ref = tags['GPS GPSLatitudeRef'].values[0]
                lon_ref = tags['GPS GPSLongitudeRef'].values[0]
                return {
                    "latitude": dms_to_decimal(lat, lat_ref),
                    "longitude": dms_to_decimal(lon, lon_ref)
                }
    except Exception as e:
        logging.error(f"EXIF read error: {str(e)}")
    return None

# Text Utilities
def is_business_card(text):
    return any(keyword in text.lower() for keyword in ['email', 'phone', 'www', '@', 'com', 'inc', 'llc'])

def parse_ocr_text(text):
    parsed = {"firstName": "", "lastName": "", "email": "", "workPhone": "", "company": "", "notes": ""}
    lines = text.split('\n')
    email_re = r'[\w\.-]+@[\w\.-]+\.\w+'
    phone_re = r'(\+?\d{1,2}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}'
    name_parts = []

    for line in lines:
        line = line.strip()
        if not parsed["email"]:
            match = re.search(email_re, line)
            if match:
                parsed["email"] = match.group()
                continue
        if not parsed["workPhone"]:
            match = re.search(phone_re, line)
            if match:
                parsed["workPhone"] = match.group()
                continue
        if not parsed["company"] and any(x in line.lower() for x in ['inc', 'llc', 'corp']):
            parsed["company"] = line
            continue
        if line.replace(" ", "").isalpha():
            name_parts.append(line)
    if name_parts:
        parsed["firstName"] = name_parts[0]
        if len(name_parts) > 1:
            parsed["lastName"] = name_parts[-1]
    return parsed

# Field Mapping
def suggest_field_mapping(df, field_definitions):
    mapping = {entity: {} for entity in field_definitions.keys()}
    columns = df.columns.str.lower()
    matched_columns = set()  # Track matched columns to avoid duplicates
    BATCH_SIZE = 500  # Process fields in batches

    for entity, fields in field_definitions.items():
        for i in range(0, len(fields), BATCH_SIZE):
            batch = fields[i:i + BATCH_SIZE]
            for field in batch:
                field_name = field.get("name", "").lower()
                for col in columns:
                    if col in matched_columns:
                        continue
                    if (field_name.replace(" ", "") in col.replace(" ", "") or
                        col in field_name.replace(" ", "")):
                        mapping[entity][field_name] = col
                        matched_columns.add(col)
                        break  # Early exit once a match is found
    return mapping

def map_fields(row, fields):
    mapped = {}
    for target, source in fields.items():
        val = row.get(source.lower())
        if pd.notna(val):
            mapped[target] = str(val)
    return mapped if mapped else None
