from flask import Flask, render_template_string, request
from werkzeug.utils import secure_filename
import os, io
import pandas as pd
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
app.config['UPLOAD_EXTENSIONS'] = ['.csv', '.pdf', '.png', '.jpg', '.jpeg']

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TaxEase Analyzer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@1/css/pico.min.css">
</head>
<body>
  <nav class="container-fluid">
    <ul><li><strong>TaxEase</strong></li></ul>
    <ul>
      <li><a href="#">Home</a></li>
      <li><a href="#upload">Upload</a></li>
    </ul>
  </nav>
  <main class="container">
    <hgroup>
      <h2>Upload Tax Documents</h2>
      <h3>CSV, PDF, or Receipt Images (JPG/PNG)</h3>
    </hgroup>
    <form method="POST" action="/upload" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.pdf,.jpg,.jpeg,.png" required>
      <button type="submit">Upload and Analyze</button>
    </form>
    {% if results %}
      <h3>Extracted Data</h3>
      <pre>{{ results }}</pre>
    {% endif %}
  </main>
  <footer class="container">
    <small><a href="#">Privacy Policy</a> • <a href="#">Terms of Service</a></small>
  </footer>
</body>
</html>
'''

def extract_from_csv(file_stream):
    df = pd.read_csv(file_stream)
    flagged = df[df.iloc[:, 1] > 10000] if df.shape[1] > 1 else pd.DataFrame()
    return f"CSV Extract:\n{df.to_string(index=False)}\n\nFlagged:\n{flagged.to_string(index=False)}" if not flagged.empty else f"CSV Extract:\n{df.to_string(index=False)}"

def extract_from_pdf(file_stream):
    doc = fitz.open(stream=file_stream.read(), filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    lines = [line for line in text.splitlines() if line.strip()]
    flagged_lines = [line for line in lines if "$" in line and any(c.isdigit() for c in line)]
    return "PDF Extract:\n" + text[:1000] + ("\n\nFlagged:\n" + "\n".join(flagged_lines) if flagged_lines else "")

def extract_from_image(file_stream):
    image = Image.open(file_stream)
    text = pytesseract.image_to_string(image)
    lines = [line for line in text.splitlines() if line.strip()]
    flagged_lines = [line for line in lines if "$" in line and any(c.isdigit() for c in line)]
    return "Image OCR:\n" + text[:1000] + ("\n\nFlagged:\n" + "\n".join(flagged_lines) if flagged_lines else "")

@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML_TEMPLATE, results=None)

@app.route('/upload', methods=['POST'])
def upload():
    uploaded_file = request.files['file']
    filename = secure_filename(uploaded_file.filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext not in app.config['UPLOAD_EXTENSIONS']:
        return "Invalid file type.", 400

    results = ""
    if ext == ".csv":
        results = extract_from_csv(uploaded_file.stream)
    elif ext == ".pdf":
        results = extract_from_pdf(uploaded_file.stream)
    elif ext in [".png", ".jpg", ".jpeg"]:
        results = extract_from_image(uploaded_file.stream)

    return render_template_string(HTML_TEMPLATE, results=results)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
