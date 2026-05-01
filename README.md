# HUST Enterprise RAG System 🔍

> **Production-grade Retrieval-Augmented Generation** — Hệ thống RAG doanh nghiệp chuyên biệt dành cho tài liệu quy định, pháp lý và văn bản nội bộ của Đại học Bách khoa Hà Nội (HUST).

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D4A017?logo=anthropic&logoColor=white)](https://anthropic.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector%20DB-FF6B6B)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 📖 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Tính năng](#-tính-năng)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Cấu trúc dự án](#-cấu-trúc-dự-án)
- [Cài đặt](#-cài-đặt)
- [Cấu hình](#-cấu-hình)
- [Chạy ứng dụng](#-chạy-ứng-dụng)
- [API Reference](#-api-reference)
- [Kiểm thử](#-kiểm-thử)
- [Lưu ý bảo mật](#-lưu-ý-bảo-mật)

---

## 🌟 Giới thiệu

**HUST Enterprise RAG System** là hệ thống RAG cấp doanh nghiệp được thiết kế để xử lý truy vấn trên tài liệu quy định, pháp lý và văn bản kỹ thuật dành riêng cho HUST. Hệ thống kết hợp:

- **Intelligent Document Ingestion**: Xử lý PDF, DOCX với chiến lược chunking thông minh
- **Semantic Search**: Tìm kiếm ngữ nghĩa với SentenceTransformers + ChromaDB
- **Multi-LLM Support**: Hỗ trợ Anthropic Claude, OpenAI GPT, Google Gemini
- **Web Crawling**: Thu thập tài liệu tự động từ các nguồn web
- **FastAPI Backend**: RESTful API với Server-Sent Events cho streaming
- **RAG Evaluation**: Đánh giá chất lượng pipeline tự động

---

## ✨ Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| 📄 **Document Processing** | Xử lý PDF, DOCX với chunking thông minh |
| 🔍 **Semantic Search** | Tìm kiếm ngữ nghĩa với local SentenceTransformers |
| 🤖 **Multi-LLM** | Hỗ trợ Claude, GPT-4o, Gemini với model selector |
| 🌐 **Web Crawler** | Thu thập và index tài liệu từ web tự động |
| ⚡ **Streaming API** | Server-Sent Events cho real-time response |
| 📊 **RAG Evaluation** | Đánh giá chất lượng retrieval và generation |
| 🎨 **Web Interface** | Giao diện người dùng hiện đại (Cohere-inspired) |

---

## 🏗️ Kiến trúc hệ thống

```
Client (Web/API)
      │
      ▼
┌─────────────────────┐
│    FastAPI Server   │  ← src/api/main.py
│    Port: 8000       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────────────────────────┐
│           RAG Pipeline                  │
├──────────────┬──────────────────────────┤
│   Ingest     │   Query & Generate       │
│  src/pipeline/ingest.py                 │
│              │  src/pipeline/generate.py│
│              │  src/pipeline/retrieve   │
└──────────────┴──────────────────────────┘
          │                    │
          ▼                    ▼
┌─────────────────┐   ┌──────────────────┐
│  ChromaDB       │   │   LLM Provider   │
│  (Local Vector  │   │  • Anthropic     │
│   Store)        │   │  • OpenAI        │
│  data/chroma_db/│   │  • Google Gemini │
└─────────────────┘   └──────────────────┘
          │
          ▼
┌─────────────────────┐
│ SentenceTransformers│
│ (Local Embeddings)  │
└─────────────────────┘
```

---

## 📁 Cấu trúc dự án

```
enterprise_rag_system/
├── rag.py                      # Entry point chính
├── requirements.txt            # Thư viện Python
├── DESIGN.md                   # Hệ thống thiết kế UI (Cohere-inspired)
├── .env                        # Biến môi trường (không commit)
│
├── src/                        # Source code chính
│   ├── api/                    # FastAPI application
│   │   ├── main.py             # FastAPI app & routing
│   │   └── routes/             # API route handlers
│   ├── pipeline/               # RAG pipeline modules
│   │   ├── ingest.py           # Document ingestion
│   │   ├── chunker.py          # Text chunking strategies
│   │   ├── embed_and_store.py  # Embedding & storage
│   │   ├── generate.py         # LLM generation (Claude/GPT)
│   │   ├── web_crawler.py      # Web document collection
│   │   ├── evaluate_rag.py     # Pipeline evaluation
│   │   ├── qa_processor.py     # Q&A processing
│   │   └── document_processor.py
│   └── web/                    # Frontend assets
│
├── data/                       # Dữ liệu ứng dụng
│   ├── raw/                    # Tài liệu gốc (PDF, DOCX)
│   ├── processed/              # Tài liệu đã xử lý
│   ├── chroma_db/              # ChromaDB vector store (local)
│   ├── crawl_logs/             # Log thu thập web
│   └── eval_results/           # Kết quả đánh giá RAG
│
├── docs/                       # Tài liệu dự án
├── _bmad-output/               # Output từ BMad AI framework
└── _bmad/                      # BMad configuration
```

---

## ⚙️ Cài đặt

### Yêu cầu hệ thống

- Python **3.10** trở lên
- RAM tối thiểu **4GB** (cho local embedding models)
- Tài khoản Anthropic / OpenAI / Google AI (ít nhất một)

### Bước 1: Clone repository

```bash
git clone <repository-url>
cd enterprise_rag_system
```

### Bước 2: Tạo và kích hoạt môi trường ảo

```bash
# Windows
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS/Linux
python -m venv venv
source venv/bin/activate
```

### Bước 3: Cài đặt thư viện

```bash
pip install -r requirements.txt

# Cài đặt Playwright browsers (cho web crawler)
playwright install chromium
```

---

## 🔑 Cấu hình

Tạo file `.env` tại thư mục gốc:

```env
# LLM Providers (cấu hình ít nhất một)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...

# Default Model
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_MODEL=claude-3-5-sonnet-20241022

# Embedding (local, không cần API key)
EMBEDDING_MODEL=all-MiniLM-L6-v2

# ChromaDB (local, không cần cấu hình thêm)
CHROMA_DB_PATH=./data/chroma_db
CHROMA_COLLECTION_NAME=regulatory_docs

# API Server
API_HOST=0.0.0.0
API_PORT=8000
```

> ⚠️ **Không bao giờ** commit file `.env` lên Git.

---

## 🚀 Chạy ứng dụng

### Khởi động API Server

```bash
# Kích hoạt môi trường ảo
.\venv\Scripts\Activate.ps1

# Chạy FastAPI server
python rag.py
# hoặc
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

API sẽ khởi động tại `http://localhost:8000`

### Ingest tài liệu

```bash
# Đặt tài liệu PDF/DOCX vào data/raw/
# Sau đó chạy ingestion
python -c "from src.pipeline.ingest import ingest_documents; ingest_documents('data/raw')"
```

---

## 📡 API Reference

### Health Check

```http
GET /health
```

### Query (Streaming)

```http
POST /api/query
Content-Type: application/json

{
  "question": "Quy định về an toàn thực phẩm là gì?",
  "model": "claude-3-5-sonnet-20241022",
  "top_k": 5
}
```

### Available Models

```http
GET /api/models
```

### Ingest Document

```http
POST /api/ingest
Content-Type: multipart/form-data

file: <PDF hoặc DOCX file>
```

Xem tài liệu API đầy đủ tại `http://localhost:8000/docs` (Swagger UI).

---

## 🧪 Kiểm thử

```bash
# Chạy test retrieval pipeline
python src/pipeline/test_retrieval.py

# Đánh giá RAG pipeline
python src/pipeline/evaluate_rag.py

# Test web crawler
python src/pipeline/web_crawler.py --test
```

---

## 🔒 Lưu ý bảo mật

- **Không commit** file `.env` hoặc bất kỳ file chứa API key
- ChromaDB và dữ liệu trong `data/` nên được exclude khỏi Git (đã có trong `.gitignore`)
- Chỉ expose API ra public internet sau khi thêm authentication middleware
- Log crawler (`data/crawl_logs/`) có thể chứa thông tin nhạy cảm

---

## 🛠️ Tech Stack

| Thành phần | Công nghệ |
|------------|-----------|
| **API Framework** | [FastAPI](https://fastapi.tiangolo.com) + Uvicorn |
| **LLM** | Anthropic Claude / OpenAI GPT / Google Gemini |
| **Embeddings** | [SentenceTransformers](https://sbert.net) (local) |
| **Vector DB** | [ChromaDB](https://www.trychroma.com) (local) |
| **Document Parsing** | PyMuPDF, python-docx |
| **Web Crawling** | Playwright + BeautifulSoup4 |
| **Data Validation** | Pydantic |
| **Streaming** | Server-Sent Events (SSE) |

---

## 📄 License

Dự án này được phát triển cho mục đích học thuật tại **Trường Đại học Bách khoa Hà Nội (HUST)**.

---

*Được xây dựng với ❤️ cho môn học Graduate Research 1*
