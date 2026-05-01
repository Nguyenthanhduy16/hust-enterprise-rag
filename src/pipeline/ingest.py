import os
import json
from pathlib import Path
from document_processor import extract_document
from chunker import RegulationChunker
from qa_processor import process_qa_directory

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

def process_all_documents():
    if not PROCESSED_DIR.exists():
        PROCESSED_DIR.mkdir(parents=True)
        
    chunker = RegulationChunker(max_chunk_size=2000)
    
    valid_exts = {".pdf", ".docx", ".txt"}
    files_to_process = []
    
    # Scan main raw directory
    if RAW_DIR.exists():
        files_to_process = [f for f in RAW_DIR.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]
    
    # Also scan crawled_web subdirectory (output from web_crawler.py)
    crawled_dir = RAW_DIR / "crawled_web"
    if crawled_dir.exists():
        crawled_files = [f for f in crawled_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]
        files_to_process.extend(crawled_files)
        if crawled_files:
            print(f"Found {len(crawled_files)} crawled web files in {crawled_dir}")
    
    if not files_to_process:
        print(f"No valid documents found in {RAW_DIR}")
        print("Please place your PDF or DOCX regulation files inside the data/raw/ directory and run again.")
        return

    all_chunks = []

    for file_path in files_to_process:
        print(f"Processing: {file_path.name}...")
        try:
            # 1. Extract raw text with PyMuPDF/python-docx
            text = extract_document(file_path)
            
            # 2. Assign document metadata
            metadata = {
                "filename": file_path.name
            }
            
            # 3. Apply structural semantic chunking
            doc_chunks = chunker.chunk_document(text, metadata)
            all_chunks.extend(doc_chunks)
            print(f" -> Extracted {len(doc_chunks)} distinct chunks based on regulations.")
            
        except Exception as e:
            print(f"Failed to process {file_path.name}: {e}")

    # 4. Process Q&A quiz files from form_qc_pl directory
    qa_dir = RAW_DIR / "form_qc_pl"
    qa_chunks = process_qa_directory(qa_dir)
    if qa_chunks:
        all_chunks.extend(qa_chunks)
        print(f"\nAdded {len(qa_chunks)} Q&A chunks from regulation quizzes.")
            
    # 5. Dump chunks to JSON for human inspection before vector embedding
    output_path = PROCESSED_DIR / "corpus_chunks.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=4)
        
    print(f"\nProcessing complete! Generated {len(all_chunks)} semantic chunks.")
    print(f"Check {output_path} to inspect citation quality before vector embedding.")

if __name__ == "__main__":
    process_all_documents()
