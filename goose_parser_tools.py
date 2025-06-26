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
                lat = tags['GPS GPSLatitude']
                lat_ref = tags['GPS GPSLatitudeRef'].values
                lon = tags['GPS GPSLongitude']
                lon_ref = tags['GPS GPSLongitudeRef'].values
                return {
                    "latitude": dms_to_decimal(lat.values, lat_ref),
                    "longitude": dms_to_decimal(lon.values, lon_ref)
                }
    except Exception as e:
        logging.error(f"EXIF extraction error: {str(e)}")
    return None

# New function to parse contact data from OCR text
def parse_contact_from_text(text):
    contact = {"name": "", "email": "", "phone": ""}

    name_match = re.search(r"Name[:\s]*([A-Za-z ,.'-]+)", text)
    email_match = re.search(r"Email[:\s]*([\w\.-]+@[\w\.-]+)", text)
    phone_match = re.search(r"Phone[:\s]*(\+?\d[\d\s\-]{7,}\d)", text)

    if name_match:
        contact["name"] = name_match.group(1).strip()
    if email_match:
        contact["email"] = email_match.group(1).strip()
    if phone_match:
        contact["phone"] = phone_match.group(1).strip()

    return contact
