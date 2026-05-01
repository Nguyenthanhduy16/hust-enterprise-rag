import fitz  # PyMuPDF
import docx
from pathlib import Path

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        # Extract text while attempting to preserve reading order natively
        text += page.get_text("text") + "\n"
    return text

def extract_text_from_docx(docx_path):
    doc = docx.Document(docx_path)
    text = "\n".join([para.text for para in doc.paragraphs])
    return text

def extract_document(file_path):
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        return extract_text_from_pdf(path)
    elif path.suffix.lower() == ".docx":
        return extract_text_from_docx(path)
    elif path.suffix.lower() == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file extension: {path.suffix}")
