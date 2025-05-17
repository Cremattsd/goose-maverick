# goose_parser_tools.py – updated for saved mapping support and per-entity mapping logic

import os
import json
import pytesseract
from PIL import Image
import pdf2image
import exifread
import re
import pandas as pd
import logging
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

MAPPING_FILE_DIR = '.'

# === OCR FUNCTIONS ===
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

# === GEO FUNCTIONS ===
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

# === TEXT UTILITIES ===
def is_business_card(text):
    return any(keyword in text.lower() for keyword in ['email', 'phone', 'www', '@', 'com', 'inc', 'llc'])

def parse_ocr_text(text):
    parsed = {"fullName": "", "email": "", "work": "", "company": ""}
    lines = text.split('\n')
    email_re = r'[\w\.-]+@[\w\.-]+\.\w+'
    phone_re = r'(\+?\d{1,2}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}'

    for line in lines:
        line = line.strip()
        if not parsed["email"]:
            match = re.search(email_re, line)
            if match: parsed["email"] = match.group(); continue
        if not parsed["work"]:
            match = re.search(phone_re, line)
            if match: parsed["work"] = match.group(); continue
        if not parsed["company"] and any(x in line.lower() for x in ['inc', 'llc', 'corp']):
            parsed["company"] = line
            continue
        if not parsed["fullName"] and line.replace(" ", "").isalpha():
            parsed["fullName"] = line
            continue
    return parsed

# === FIELD MAPPING ===
def load_saved_mapping(name=None):
    try:
        filename = f"saved_mapping_{name}.json" if name else "saved_mapping.json"
        filepath = os.path.join(MAPPING_FILE_DIR, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Mapping load error: {str(e)}")
    return {"contacts": {}}

def suggest_field_mapping(df):
    try:
        with open(os.path.join(MAPPING_FILE_DIR, 'static/realnex_fields.json')) as f:
            reference_fields = json.load(f)
    except Exception as e:
        logging.warning(f"Could not load reference fields: {e}")
        reference_fields = {}

    mapping = {k: {} for k in reference_fields.keys()}
    columns = df.columns.str.lower()

    for entity, fields in reference_fields.items():
        for field in fields:
            for col in columns:
                if field.lower().replace(" ", "") in col.replace(" ", ""):
                    mapping[entity][field] = col
    return mapping

def map_fields(row, fields):
    mapped = {}
    for target, source in fields.items():
        val = row.get(source.lower())
        if pd.notna(val):
            mapped[target] = str(val)
    return mapped if mapped else None

def auto_map_dataframe(df, map_name=None):
    df.columns = df.columns.str.lower()
    mapping = load_saved_mapping(map_name)
    if not mapping.get("contacts"):
        mapping = suggest_field_mapping(df)
    result = []
    for _, row in df.iterrows():
        mapped = map_fields(row, mapping.get("contacts", {}))
        if mapped:
            result.append(mapped)
    return result
