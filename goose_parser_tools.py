import pytesseract
from PIL import Image
import pdf2image
import exifread
import re
import pandas as pd


def extract_text_from_image(image_path):
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from image: {str(e)}")
        return ""


def extract_text_from_pdf(pdf_path):
    try:
        images = pdf2image.convert_from_path(pdf_path)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {str(e)}")
        return ""


def extract_exif_location(image_path):
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f)
            if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                lat = tags['GPS GPSLatitude'].values
                lon = tags['GPS GPSLongitude'].values
                return {"latitude": str(lat), "longitude": str(lon)}
        return None
    except Exception as e:
        print(f"Error extracting EXIF location: {str(e)}")
        return None


def is_business_card(text):
    keywords = ['email', 'phone', 'www', '@', 'com', 'inc', 'llc']
    return any(keyword in text.lower() for keyword in keywords)


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
        if not parsed["fullName"] and line.replace(" ", "").isalpha():
            parsed["fullName"] = line
            continue
        if not parsed["company"] and any(kw in line.lower() for kw in ['inc', 'llc', 'corp']):
            parsed["company"] = line
            continue
        if not parsed["work"] and any(kw in line.lower() for kw in ['work', 'office', 'phone']):
            parsed["work"] = line
            continue
    return parsed


def suggest_field_mapping(df):
    mapping = {"contacts": {}, "companies": {}, "properties": {}, "spaces": {}, "projects": {}}
    columns = df.columns.str.lower()

    if "name" in columns:
        mapping["contacts"]["fullName"] = "name"
    if "email" in columns:
        mapping["contacts"]["email"] = "email"
    if "phone" in columns:
        mapping["contacts"]["work"] = "phone"

    if "company" in columns:
        mapping["companies"]["name"] = "company"

    return mapping


def map_fields(row, fields):
    mapped = {}
    for target_field, source_field in fields.items():
        if source_field.lower() in row and pd.notna(row[source_field.lower()]):
            mapped[target_field] = str(row[source_field.lower()])
    return mapped if mapped else None