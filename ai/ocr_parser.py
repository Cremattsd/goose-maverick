# ai/ocr_parser.py
import pytesseract
import fitz  # PyMuPDF
import pandas as pd
import os

def parse_uploaded_file(filepath):
    if filepath.lower().endswith('.pdf'):
        return parse_pdf(filepath=filepath)
    elif filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
        return parse_image(filepath=filepath)
    elif filepath.lower().endswith(('.xls', '.xlsx')):
        return parse_excel(filepath=filepath)
    else:
        return {"error": "Unsupported file format"}

def parse_pdf(filepath):
    import fitz
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text = page.get_text()
        extracted_data = {"pdf_text": text}
    return extracted_data

def parse_image(filepath):
    from PIL import Image
    import pytesseract
    text = pytesseract.image_to_string(Image.open(filepath))
    return {"text": text}

def parse_excel(filepath):
    import pandas as pd
    df = pd.read_excel(filepath)
    return df.to_dict(orient="records")

# this wrapper ensures we have the entry function explicitly defined:
def parse_uploaded_file(filepath):
    return parse_uploaded_file(filepath)
