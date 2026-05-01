# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Summary

**HUST Regulation QA** — A Vietnamese-language RAG chatbot for Hanoi University of Science and Technology (HUST) students. It answers questions about academic regulations with exact citations to `Chương/Điều/Khoản`. The core pipeline (`src/pipeline/`) is complete. The next phase is a **FastAPI API server + Vanilla JS web UI** (`src/api/`, `src/web/`).

## Commands

All pipeline scripts must be run from the repo root. They import each other by filename (no package), so add `src/pipeline` to `PYTHONPATH` or run them via the module path shown below.

```bash
# Activate venv first
source venv/Scripts/activate   # Windows Git Bash / bash

# Step 1 — Crawl HUST student handbook (SPA, requires Playwright)
python src/pipeline/web_crawler.py
python src/pipeline/web_crawler.py --items 1 3 8   # selective items
python src/pipeline/web_crawler.py --include-regulations --visible  # debug mode

# Step 2 — Chunk documents (PDF/DOCX/TXT + Q&A quiz files)
cd src/pipeline && python ingest.py   # writes data/processed/corpus_chunks.json

# Step 3 — Embed and store into ChromaDB
cd src/pipeline && python embed_and_store.py   # writes data/chroma_db/

# Test retrieval (inspect ranked results without LLM)
cd src/pipeline && python test_retrieval.py

# Interactive chatbot (retrieval + LLM generation loop)
cd src/pipeline && python generate.py

# Run the API server (once src/api/ exists)
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Required `.env` keys:**
```
ANTHROPIC_API_KEY=...     # generation (claude-opus-4-7 default)
GEMINI_API_KEY=...        # legacy; no longer required for current embedding model
```

## Architecture

### Pipeline Data Flow

```
data/raw/ (PDF/DOCX/TXT)
data/raw/crawled_web/     ← web_crawler.py (Playwright SPA crawler)
data/raw/form_qc_pl/      ← Q&A quiz .txt files (JS-format)
         │
         ▼
document_processor.py     — PyMuPDF / python-docx text extraction
         │
         ▼
chunker.py                — VietnameseRegulationCleaner → RegulationChunker
         │                   structural boundaries: Chương > Mục > Điều > Phụ lục
         ▼
data/processed/corpus_chunks.json   ← human-inspectable checkpoint
         │
         ▼
embed_and_store.py        — SentenceTransformer("truro7/vn-law-embedding")
                            → chromadb.PersistentClient → collection "hust_regulations_v2"
         │
         ▼
data/chroma_db/           ← persistent vector store

Query path:
test_retrieval.py::test_retrieval()
  → ChromaDB.query(fetch_k=10) → domain_rerank() → top-k chunks
  → generate.py::generate_answer() → OpenAI chat completion (gpt-4o-mini)
  → 4-step chain-of-thought prompt → Vietnamese answer with citations
```

### Key Source Files

| File | Role |
|---|---|
| `chunker.py` | `RegulationChunker` + `VietnameseRegulationCleaner`; the structural heart of the system |
| `test_retrieval.py` | `domain_rerank()` scoring function + `test_retrieval()` display utility |
| `generate.py` | `generate_answer()` + interactive chatbot loop with multi-query decomposition |
| `embed_and_store.py` | One-shot indexing script; batch-upserts to ChromaDB |
| `web_crawler.py` | Playwright SPA crawler for `sv-ctt.hust.edu.vn`; `HUSTHandbookCrawler` + `HUSTRegulationsCrawler` |
| `qa_processor.py` | Parses JS-format quiz answer files into corpus chunks |

### Planned New Layers (not yet built)

```
src/api/
  main.py            — FastAPI app factory; lifespan initializes ChromaDB singleton
  routes/chat.py     — POST /api/v1/chat/query → SSE streaming
  routes/admin.py    — POST /api/v1/admin/ingest (X-Admin-Key header auth)
src/web/
  index.html / style.css / app.js   — Vanilla JS, EventSource SSE, marked.js for markdown
```

## Critical Implementation Rules

### ChromaDB Metadata Schema (binding contract)
Every chunk written to ChromaDB and every read from it must use exactly these 8 fields:
`document`, `chapter`, `section`, `article`, `appendix`, `table_label`, `part`, `citation`

### Structural Chunking Boundaries
`chunker.py` splits at structural headings only — **never by token count**:
- `Phụ lục` (Appendix) → new chunk **and** resets `article` context
- `Chương` (Chapter) → new chunk, resets section/article/appendix
- `Mục` (Section) → new chunk
- `Điều` (Article) → new chunk, new `article` context
- `Khoản` (Clause) → stays inside its parent `Điều` chunk
- `Bảng` (Table) → adds `table_label` metadata only; **never** a chunk boundary

Heading regexes use `(?:[:\.\s]|$)` at the end to handle trailing punctuation gracefully — do not simplify this.

### Reranker Scoring Formula
`domain_rerank()` in `test_retrieval.py` uses this additive formula:
```
final_score = 0.50 × vec_similarity   (L2 → similarity: 1/(1+l2_dist))
            + 0.25 × kw_overlap
            + 0.15 × domain_score
            + 0.10 × id_boost         (cohort IDs: k68/k70 or YYYY-YYYY pattern)
            + table_boost             (0.3 if query hints at table data)
            + num_boost               (0.2 per matching number)
```
Do not change the weights or the `1/(1+l2_dist)` conversion without careful testing. The `doc_ids_in_query` regex `r'\b(k\d{2}|\d{4}-\d{4})\b'` is intentional for cohort-document matching.

### ChromaDB Client Lifecycle
`PersistentClient` must be instantiated **once at app startup** and stored as `app.state` (FastAPI lifespan pattern). Never instantiate per-request — causes file lock conflicts on Windows.

### LLM Generation
`generate.py` uses **Anthropic** (`claude-opus-4-7` default) with adaptive thinking enabled and streaming via `.stream()` + `.get_final_message()`. Only `text` blocks are extracted from the response — `thinking` blocks are silently filtered out. Retry logic: 3 attempts, exponential backoff starting at 4s, triggers on `RateLimitError` and `APIStatusError` 5xx. Gemini API key is legacy; embeddings use the local `truro7/vn-law-embedding` SentenceTransformer model.

### Vietnamese Text
UTF-8 must be preserved end-to-end: PDF extraction, chunking, prompt assembly, JSON output, API responses. The `VietnameseRegulationCleaner` drops noise lines (page numbers, dot leaders, short fragments) but preserves all Vietnamese diacritics.

### API Design (when building `src/api/`)
- Base path: `/api/v1/`
- Chat endpoint streams SSE: `{"type": "token"|"citations"|"done", ...}`
- Admin routes protected via `X-Admin-Key` header dependency
- CORS: allow all origins for MVP
- Serve `src/web/` via `StaticFiles` mount at root `/`
