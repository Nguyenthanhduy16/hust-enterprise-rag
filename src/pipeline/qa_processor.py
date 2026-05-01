"""
Pre-processor for Q&A regulation quiz files (form_qc_pl).

Parses JavaScript-style answer dictionaries into structured chunks
optimised for RAG retrieval.  Each question–answer pair becomes one chunk
so the retriever can match user questions against known quiz items.
"""

import re
import uuid
import json
from pathlib import Path


def parse_qa_js_file(file_path: Path) -> list[dict]:
    """
    Parse a JavaScript-style `const answers = { ... };` file into a list
    of {"question": ..., "answers": [...]} dicts.

    Strategy: use regex to extract key-value pairs since the file mixes
    single and double quotes (valid JS but not valid JSON).
    """
    text = file_path.read_text(encoding="utf-8")

    # Match patterns like:
    #   "Question text": ["Answer 1", "Answer 2"],
    #   'Question with "quotes"': ["Answer"],
    # Keys can be single or double-quoted; values are arrays of strings.
    qa_pairs = []

    # Pattern: captures the key (in single or double quotes) and
    # then the array value on the same or following lines
    # We match key: [value_array] groups
    pattern = re.compile(
        r"""(?:"|')(.+?)(?:"|')\s*:\s*\[([^\]]*)\]""",
        re.DOTALL
    )

    for match in pattern.finditer(text):
        question = match.group(1).strip()
        raw_answers = match.group(2)

        # Extract individual answer strings from inside the array
        answer_pattern = re.compile(r'(?:"|\')\s*(.+?)\s*(?:"|\')')
        answers = [m.group(1).strip() for m in answer_pattern.finditer(raw_answers)]

        if question and answers:
            qa_pairs.append({
                "question": question,
                "answers": answers,
            })

    return qa_pairs


def qa_pairs_to_chunks(qa_pairs: list[dict], source_filename: str) -> list[dict]:
    """
    Convert parsed Q&A pairs into chunk dicts compatible with the
    existing corpus_chunks.json schema used by embed_and_store.py.

    Each chunk contains a question + its correct answer(s) formatted as
    readable text so the embedding model can match semantic similarity.
    """
    chunks = []

    for qa in qa_pairs:
        q = qa["question"]
        answers = qa["answers"]

        # Build a single readable content block
        answer_text = "\n".join(f"- {a}" for a in answers)
        content = f"Câu hỏi: {q}\nĐáp án đúng:\n{answer_text}"

        chunk = {
            "id":          str(uuid.uuid4()),
            "document":    source_filename,
            "chapter":     "Kiểm tra quy chế - Pháp luật",
            "chapter_num": "",
            "section":     "",
            "article":     "",
            "article_num": "",
            "appendix":    "",
            "table_label": "",
            "part":        "1/1",
            "content":     content,
            "citation":    f"{source_filename} > Kiểm tra quy chế - Pháp luật",
        }
        chunks.append(chunk)

    return chunks


def process_qa_directory(qa_dir: Path) -> list[dict]:
    """
    Scan a directory for Q&A files (.txt) in JS format and return
    all chunks ready for embedding.
    """
    if not qa_dir.exists():
        return []

    all_chunks = []
    for f in sorted(qa_dir.iterdir()):
        if f.suffix.lower() != ".txt":
            continue
        print(f"Processing Q&A file: {f.name}...")
        qa_pairs = parse_qa_js_file(f)
        if qa_pairs:
            chunks = qa_pairs_to_chunks(qa_pairs, f.name)
            all_chunks.extend(chunks)
            print(f"  -> Extracted {len(chunks)} Q&A chunks.")
        else:
            print(f"  -> No Q&A pairs found.")

    return all_chunks


# ---------------------------------------------------------------------------
# Quick standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    qa_dir = PROJECT_ROOT / "data" / "raw" / "form_qc_pl"

    chunks = process_qa_directory(qa_dir)
    print(f"\nTotal Q&A chunks: {len(chunks)}")
    if chunks:
        print(f"\nSample chunk:\n{chunks[0]['content']}")
