---
stepsCompleted: [1]
inputDocuments: []
session_topic: 'HUST Regulations RAG Chatbot'
session_goals: 'Determine embedding model, vector database, chunking strategy, and MVP system architecture'
selected_approach: 'practical-implementation'
techniques_used: ['direct-architecture-recommendations']
ideas_generated: ['Supabase pgvector', 'Regex semantic chunking (Chương/Điều)', 'gpt-4o-mini', 'text-embedding-3-small', 'FastAPI backend']
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** BOSS
**Date:** 2026-04-11

## Session Overview

**Topic:** HUST Regulations RAG Chatbot with Cloud API and PDF citations
**Goals:** Determine embedding model, vector database, chunking strategy, and MVP system architecture

### Context Guidance

_No context file provided_

### Session Setup

User initiated the session with specific project requirements. Focus is on technical architecture and RAG optimization for PDF-based regulation data.

## Technical Recommendations (MVP)

Below is a highly practical, implementation-focused architecture tailored for an MVP student project with your specific constraints.

### 1. RAG Type
**Standard RAG with Metadata Filtering** (also known as Metadata-augmented RAG).
Since administrative documents are highly structured, you do not need complex Agentic RAG yet. Instead, structure your pipeline so the retriever filters by the document name or type before performing the vector search. This ensures rules from "Quy định học vụ" do not get mixed up with "Quy chế Ký túc xá".

### 2. Embedding Model
**OpenAI `text-embedding-3-small`**
- **Why:** Extremely cheap, fast, great context length, and works surprisingly well for Vietnamese out of the box. As a cloud API, it requires zero setup.
- **Alternative:** `BAAI/bge-m3` (Multilingual) if you decide to host the embeddings yourself or use a Hugging Face endpoint.

### 3. Vector Database
**Supabase (with pgvector)** or **Pinecone (Serverless)**
- **Why Supabase:** This is perfect for an MVP web app. It gives you a postgres database (to store chat history), a Vector DB (pgvector) to store your embeddings, and authentication (if you decide to add role-based access later) all in one free tier.
- **Why Pinecone:** If you strictly want *just* a vector database, the Pinecone free serverless tier is the easiest to set up in pure Python.

### 4. Chunking Strategy (Crucial for HUST Regulations)
**Semantic/Structural Chunking based on Regex.**
Do not use standard fixed-size chunking (like splitting every 500 characters), as this will cut right through the middle of a "Điều" (Article).

Vietnamese administrative documents are very predictable. Use Regex to split the text based on headings:
- **Chunk Level:** Split your documents so that **each Chunk equals 1 "Điều"**.
- **Metadata:** Every chunk MUST have metadata attached before embedding. For example:
  ```json
  {
    "document": "Quy chế đào tạo đại học 2023",
    "chapter": "Chương II: Tổ chức đào tạo",
    "article": "Điều 8: Đăng ký học phần",
    "content": "...(Toàn bộ nội dung của Điều 8)..."
  }
  ```
This ensures that when the LLM answers, it can directly cite "Theo Điều 8, Chương II, Quy chế đào tạo đại học 2023..." using the metadata.

### 5. Prompt Strategy & Guardrails (Anti-Hallucination)
- **Hard Prompting:**
  ```text
  Bạn là trợ lý AI ảo hỗ trợ sinh viên ĐHBK Hà Nội. Nhiệm vụ của bạn là trả lời câu hỏi DỰA VÀO các tài liệu quy định được cung cấp dưới đây.
  
  [CONTEXT]
  {retrieved_chunks}
  [/CONTEXT]
  
  Quy tắc bắt buộc:
  1. CHỈ sử dụng thông tin trong [CONTEXT]. Tuyệt đối không tự bịa thông tin.
  2. Nếu [CONTEXT] không chứa đủ thông tin để trả lời, HÃY TỪ CHỐI và nói: "Xin lỗi, tôi không tìm thấy thông tin đủ cơ sở trong quy định để trả lời câu hỏi này."
  3. Ở cuối câu trả lời, luôn trích dẫn nguồn dựa theo thông tin trong [CONTEXT].
  ```
- **Cosign Similarity Threshold:** Set a threshold (e.g., > 0.70) in your Vector DB query. If no chunks pass the similarity threshold, skip calling the LLM entirely and return your fallback message.

### 6. System Architecture (MVP)
A straightforward modern stack that is easy for a student project:
- **Frontend:** Next.js (React) or simply HTML/Vanilla JS with Bootstrap if you want to be extremely lightweight. Connect via REST API.
- **Backend/Orchestrator:** **FastAPI (Python)** using **LlamaIndex** or **LangChain**. (LlamaIndex is highly recommended for structured document RAG).
- **Core Cloud APIs:** OpenAI API for both Embeddings (`text-embedding-3-small`) and Generation (`gpt-4o-mini` - it is much cheaper and faster than GPT-4, perfectly capable of reading Vietnamese context).

### 7. Implementation Roadmap
- **Step 1: Data Preparation (Week 1)**
  - Convert PDF to Markdown/Text (Use tools like `pdfplumber` or `marker`).
  - Write regex scripts to chunk the text by "Điều" and extract metadata.
- **Step 2: Vector Search Pipeline (Week 2)**
  - Set up Supabase / Pinecone.
  - Embed chunks and upload them to the Vector DB along with metadata.
  - Test retrieval manually (send a query and see if the correct "Điều" comes up).
- **Step 3: Backend Integration (Week 3)**
  - Build the FastAPI server.
  - Integrate Langchain/LlamaIndex.
  - Write the strict anti-hallucination prompt.
- **Step 4: Chat Interface (Week 4)**
  - Build simple chat UI.
  - Display LLM response, along with a "Citations" section at the bottom dynamically rendering the metadata of the retrieved chunks.
