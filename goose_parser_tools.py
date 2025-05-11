import pytesseract
from PIL import Image
import pdf2image
import exifread
import re
import pandas as pd

# === OCR from image ===
def extract_text_from_image(image_path):
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"[OCR ERROR] Image: {str(e)}")
        return ""

# === OCR from PDF ===
def extract_text_from_pdf(pdf_path):
    try:
        images = pdf2image.convert_from_path(pdf_path)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
        return text.strip()
    except Exception as e:
        print(f"[OCR ERROR] PDF: {str(e)}")
        return ""

# === EXIF location (if available) ===
def extract_exif_location(image_path):
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f)
            if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                lat = tags['GPS GPSLatitude'].values
                lon = tags['GPS GPSLongitude'].values
                return {
                    "latitude": float(lat[0].num) + float(lat[1].num)/60 + float(lat[2].num)/3600,
                    "longitude": float(lon[0].num) + float(lon[1].num)/60 + float(lon[2].num)/3600
                }
        return None
    except Exception as e:
        print(f"[EXIF ERROR] {str(e)}")
        return None

# === Detect business card based on common keywords ===
def is_business_card(text):
    keywords = ['email', 'phone', 'www', '@', 'com', 'inc', 'llc']
    return any(keyword in text.lower() for keyword in keywords)

# === Parse OCR text into contact-like fields ===
def parse_ocr_text(text):
    parsed = {"fullName": "", "email": "", "work": "", "company": ""}
    lines = text.split('\n')
    email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
    
    for line in lines:
        line = line.strip()
        if not parsed["email"]:
            email_match = re.search(email_pattern, line)
            if email_match:
                parsed["email"] = email_match.group()
                continue
        if not parsed["fullName"] and line.replace(" ", "").isalpha() and len(line.split()) >= 2:
            parsed["fullName"] = line
            continue
        if not parsed["company"] and any(kw in line.lower() for kw in ['inc', 'llc', 'corp']):
            parsed["company"] = line
            continue
        if not parsed["work"] and any(kw in line.lower() for kw in ['work', 'office', 'phone', 'tel']):
            parsed["work"] = line
            continue

    return parsed

# === Suggest field mappings from Excel/Pandas DataFrame ===
def suggest_field_mapping(df):
    mapping = {"contacts": {}, "companies": {}, "properties": {}, "spaces": {}, "projects": {}}
    columns = df.columns.str.lower()

    # Contact mapping
    if "name" in columns:
        mapping["contacts"]["fullName"] = "name"
    if "email" in columns:
        mapping["contacts"]["email"] = "email"
    if "phone" in columns:
        mapping["contacts"]["work"] = "phone"
    
    # Company mapping
    if "company" in columns:
        mapping["companies"]["name"] = "company"

    return mapping

# === Apply field mapping for each row ===
def map_fields(row, fields):
    mapped = {}
    for target_field, source_field in fields.items():
        if source_field.lower() in row and pd.notna(row[source_field.lower()]):
            mapped[target_field] = str(row[source_field.lower()])
    return mapped if mapped else None
