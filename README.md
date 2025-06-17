# TaxEase Analyzer

A Flask web app to upload and audit tax documents — CSVs, PDFs, and scanned receipts. It highlights amounts over $10,000 and extracts data using OCR or text parsing.

## Features

- CSV file parser and flagging
- PDF text extraction
- OCR for receipt image text
- In-browser display with PicoCSS UI

## Running Locally

1. Install dependencies:
```bash
pip install flask pandas pytesseract PyMuPDF pillow
