import re
import pytesseract
import exifread
import pandas as pd
from PIL import Image
from pdf2image import convert_from_path
from geopy.geocoders import Nominatim

# Initialize geocoder
geolocator = Nominatim(user_agent="realnex_goose")

def extract_text_from_image(image_path):
    try:
        return pytesseract.image_to_string(Image.open(image_path))
    except Exception as e:
        print(f"Image OCR failed: {str(e)}")
        return ""

def extract_text_from_pdf(pdf_path):
    try:
        images = convert_from_path(pdf_path)
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img)
        return text
    except Exception as e:
        print(f"PDF OCR failed: {str(e)}")
        return ""

def extract_exif_location(image_path):
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f)
        def _deg(v):
            d, m, s = v.values
            return d.num/d.den + m.num/m.den/60 + s.num/s.den/3600
        if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
            lat, lon = _deg(tags['GPS GPSLatitude']), _deg(tags['GPS GPSLongitude'])
            if tags['GPS GPSLatitudeRef'].values != 'N': lat = -lat
            if tags['GPS GPSLongitudeRef'].values != 'E': lon = -lon
            try:
                location = geolocator.reverse((lat, lon), exactly_one=True)
                return {"lat": lat, "lon": lon, "address": location.address if location else None}
            except Exception as e:
                print(f"Geocoding failed: {str(e)}")
                return {"lat": lat, "lon": lon, "address": None, "error": str(e)}
        return None
    except Exception as e:
        print(f"EXIF extraction failed: {str(e)}")
        return None

def is_business_card(text):
    return "@" in text and any(c.isdigit() for c in text) and any(len(line.split()) >= 2 for line in text.splitlines())

def parse_ocr_text(text):
    lines = text.splitlines()
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    phone_pattern = r'\b\d{3}-\d{3}-\d{4}\b'
    name = next((l for l in lines if len(l.split()) >= 2 and not re.search(email_pattern, l) and not re.search(phone_pattern, l)), "")
    email = next((l for l in lines if re.search(email_pattern, l)), "")
    phone = next((l for l in lines if re.search(phone_pattern, l)), "")
    company = next((l for l in lines if "inc" in l.lower() or "llc" in l.lower() or "corp" in l.lower()), "")
    return {
        "fullName": name.strip(),
        "email": email.strip(),
        "work": phone.strip(),
        "company": company.strip()
    }

def suggest_field_mapping(df):
    columns = df.columns.tolist()
    mapping = {
        "contacts": {},
        "companies": {}
    }
    for col in columns:
        col_lower = col.lower()
        if "name" in col_lower:
            mapping["contacts"]["fullName"] = col
        elif "email" in col_lower:
            mapping["contacts"]["email"] = col
        elif "phone" in col_lower or "work" in col_lower:
            mapping["contacts"]["work"] = col
        elif "company" in col_lower or "org" in col_lower:
            mapping["companies"]["name"] = col
    return mapping

def map_fields(data, mapping):
    mapped = {}
    for crm_field, excel_col in mapping.items():
        if excel_col in data:
            mapped[crm_field] = data[excel_col]
    return mapped
