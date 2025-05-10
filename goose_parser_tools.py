# goose_parser_tools.py – Handles PDFs, Excels, and PDF Logs

import fitz  # PyMuPDF
import pandas as pd
from fpdf import FPDF
import os
from datetime import datetime

# === 1. Parse PDF Flyer ===
def parse_flyer_text(filepath):
    doc = fitz.open(filepath)
    text = "\n".join(page.get_text() for page in doc)
    return text

def extract_property_from_flyer(text):
    lines = text.splitlines()
    props = {
        "address": next((l for l in lines if any(w in l.lower() for w in ["street", "ave", "road"])), ""),
        "city": next((l for l in lines if "," in l and any(s in l for s in ["CA", "TX", "NY"])), ""),
        "squareFeet": next((l for l in lines if "sf" in l.lower() or "sq ft" in l.lower()), "")
    }
    return props

# === 2. Parse Excel ===
def parse_excel_contacts(filepath):
    df = pd.read_excel(filepath)
    results = []
    for _, row in df.iterrows():
        result = {
            "fullName": row.get("Full Name", ""),
            "email": row.get("Email", ""),
            "work": row.get("Phone", ""),
            "organizationId": row.get("Company", ""),
            "address1": row.get("Address", ""),
            "city": row.get("City", ""),
            "state": row.get("State", ""),
            "zipCode": str(row.get("Zip", ""))
        }
        results.append(result)
    return results

# === 3. Generate PDF Report ===
class ImportReportPDF(FPDF):
    def header(self):
        self.set_font("Arial", 'B', 14)
        self.cell(0, 10, "Goose Import Report", ln=True, align="C")
        self.set_font("Arial", '', 10)
        self.cell(0, 10, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align="C")
        self.ln(10)

    def add_log(self, data):
        self.set_font("Arial", '', 10)
        for key, value in data.items():
            self.set_font("Arial", 'B', 11)
            self.cell(0, 10, f"{key.capitalize()}:", ln=True)
            self.set_font("Arial", '', 10)
            if isinstance(value, list):
                for item in value:
                    self.cell(0, 8, f"- {item}", ln=True)
            else:
                self.multi_cell(0, 8, str(value))
            self.ln(3)



def generate_pdf_log(log_data, output_path="import_report.pdf"):
    pdf = ImportReportPDF()
    pdf.add_page()
    pdf.add_log(log_data)
    pdf.output(output_path)
    return output_path

# === Example Usage ===
if __name__ == "__main__":
    flyer_text = parse_flyer_text("example_flyer.pdf")
    print("Flyer Extract:", extract_property_from_flyer(flyer_text))

    parsed_contacts = parse_excel_contacts("contacts.xlsx")
    print("Parsed Excel:", parsed_contacts[:2])

    log = {
        "file": "example_flyer.pdf",
        "created": ["Property: 123 Main St", "Contact: Joe Smith"],
        "matched": ["Company: Acme Inc"],
        "notes": "Uploaded via Goose Prime"
    }
    generate_pdf_log(log)
    print("Report saved.")
