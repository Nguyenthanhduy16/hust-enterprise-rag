---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - '_bmad-output/planning-artifacts/prd.md'
  - '_bmad-output/project-context.md'
workflowType: 'architecture'
project_name: 'enterprise_rag_system'
user_name: 'BOSS'
date: '2026-04-11'
lastStep: 8
status: 'complete'
completedAt: '2026-04-11'
---

# Architecture Decision Document — HUST Regulation QA

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

---

## Project Context Analysis

### Requirements Overview

**Functional Requirements (18 total):**
- **Chat Interaction (FR1-5):** Stateless query → grounded answer → citations displayed per turn
- **Retrieval (FR6-9):** Structural chunking across Chương/Mục/Điều boundaries; cohort reranking (K68/K70); table metadata preservation
- **Generation (FR10-12):** LLM output grounded in retrieved context only; strict refusal on low-evidence; inline citation IDs in response
- **Administration (FR13-16):** DOCX/PDF ingestion upload; metadata tagging (year, cohort); ingest trigger; chunk anomaly alerts
- **Resilience (FR17-18):** Retry queue on LLM rate-limit; graceful UI error messages on service outage

**Non-Functional Requirements (critical architectural drivers):**
- **NFR-P1/P2 (Latency):** TTFT < 3s, full response < 8s → mandates **async FastAPI** and **Server-Sent Events (SSE)** streaming
- **NFR-S2 (Access Control):** Students get read-only access; Admin-only write/mutation access → **route-level RBAC** on the API
- **NFR-R1 (Backoff):** Exponential backoff, max 3 retries on HTTP 429 → partially implemented in `generate.py`, must be formalized
- **NFR-R2 (Persistence):** ChromaDB on persistent storage volume → constrains deployment topology (no in-memory mode)

**Scale & Complexity:**
- Primary domain: Full-stack, API-first, AI-integrated (Python backend + HTML/JS frontend)
- Complexity level: **Medium-High**
- Estimated architectural components: 5 (FastAPI API server, RAG Pipeline, ChromaDB, Gemini APIs, Web Chat UI)

### Technical Constraints & Dependencies

- **Python ecosystem locked:** PyMuPDF 1.24.0, chromadb, google-genai, python-dotenv 1.0.1
- **Dual Gemini quota segregation:** `models/gemini-embedding-001` and `gemini-2.0-flash` (generation) are separate external dependencies with independent rate limits and retry strategies
- **ChromaDB must be PersistentClient:** `chromadb.PersistentClient(path=...)` — never in-memory — to satisfy NFR-R2
- **Vietnamese UTF-8 throughout:** PDF/DOCX parsing, chunking, prompt assembly, and API responses must preserve Vietnamese characters end-to-end
- **Metadata schema is a binding contract:** The 8-field schema (`document`, `chapter`, `section`, `article`, `appendix`, `table_label`, `part`, `citation`) must be identical across ingestion, retrieval, and generation layers

### Cross-Cutting Concerns Identified

| Concern | Affected Components |
|---|---|
| API Rate-limit resilience | Embedding layer, Generation layer, Ingestion pipeline |
| Vietnamese text encoding | PDF parser, Chunker, Prompt builder, REST API responses |
| Metadata schema consistency | `embed_and_store.py`, `test_retrieval.py`, `generate.py` |
| CORS policy | FastAPI server must allow Web UI origin |
| Error propagation | Pipeline errors must surface as user-friendly UI messages (FR18) |
| Streaming output | Generation → FastAPI SSE → Web UI (required for NFR-P1) |

---

## Starter Template Evaluation

### Primary Technology Domain

**Full-stack, API-first brownfield Python system.** No scaffolding CLI is required — the existing pipeline IS the foundation. The architecture extends it with a new API layer and a lightweight Web UI.

### Selected Approach: Extend Existing Python Project

**Rationale:** The backend core (`chunker.py`, `embed_and_store.py`, `test_retrieval.py`, `generate.py`) is already functional and tested. Introducing a new framework scaffold would conflict with the existing module structure. The optimal approach is to add new directories to the existing `src/` tree.

**Architectural Decisions Provided by This Approach:**

| Layer | Technology | Rationale |
|---|---|---|
| API Framework | `FastAPI` (async) | Native async, SSE support, auto OpenAPI docs, CORS middleware |
| ASGI Server | `uvicorn` | Production-grade, compatible with FastAPI |
| Web UI | Vanilla HTML + CSS + JS | Zero build step, fast to ship, sufficient for demo |
| Package Manager | `pip` + `requirements.txt` | Consistent with existing project |
| Entry Point | `src/api/main.py` | New file, does not conflict with pipeline |

**Recommended Project Structure Extension:**
```
enterprise_rag_system/
├── src/
│   ├── pipeline/           ✅ Existing — do NOT restructure
│   │   ├── chunker.py
│   │   ├── embed_and_store.py
│   │   ├── generate.py
│   │   ├── ingest.py
│   │   └── test_retrieval.py
│   ├── api/                🆕 NEW — FastAPI server
│   │   ├── __init__.py
│   │   ├── main.py         App factory, CORS, lifespan
│   │   └── routes/
│   │       ├── chat.py     POST /api/v1/chat/query (SSE stream)
│   │       └── admin.py    POST /api/v1/admin/ingest (stub for Phase 3)
│   └── web/                🆕 NEW — Chat UI served by FastAPI
│       ├── index.html
│       ├── style.css
│       └── app.js
├── data/                   ✅ Existing
├── .env
└── requirements.txt        🔄 Update: add fastapi, uvicorn[standard]
```

**Note:** Project initialization story = create `src/api/` and `src/web/` directories and `requirements.txt` update.

---

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- API contract (endpoint paths, request/response schemas) — blocks frontend development
- Streaming strategy (SSE vs WebSocket) — required for NFR-P1
- State management for ChromaDB client (singleton vs per-request) — affects performance and concurrency

**Important Decisions (Shape Architecture):**
- Authentication model for MVP vs Phase 2
- Error response schema standardization
- CORS configuration scope

**Deferred Decisions (Post-MVP):**
- SSO via `@hust.edu.vn` (Phase 2 per roadmap)
- Multi-user conversation history persistence (Phase 2)
- Admin Dashboard full implementation (Phase 3)

---

### Data Architecture

| Decision | Choice | Rationale |
|---|---|---|
| Vector Store | ChromaDB `PersistentClient` | Already implemented; NFR-R2 mandates persistent volume |
| Metadata Schema | 8-field binding contract | `document`, `chapter`, `section`, `article`, `appendix`, `table_label`, `part`, `citation` |
| Processed Data | JSON file (`corpus_chunks.json`) | Intermediate store between chunker and vector DB |
| ChromaDB Collection | `hust_regulations` (single) | All docs share one collection; cohort filtering done at rerank layer |
| Caching Strategy | None (MVP) | ChromaDB query latency is acceptable; defer Redis caching to Phase 2 |

**ChromaDB Client Lifecycle (Critical):**
The `PersistentClient` must be initialized **once at FastAPI app startup** using the `lifespan` context manager and stored as application state. Never instantiate per-request — this causes file lock conflicts on Windows and performance degradation everywhere.

```python
# src/api/main.py pattern
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    app.state.collection = app.state.chroma_client.get_collection("hust_regulations", ...)
    yield
    # cleanup on shutdown if needed
```

---

### Authentication & Security

| Decision | MVP Choice | Future (Phase 2) |
|---|---|---|
| Student Auth | **None** (open access for demo) | Google OAuth2 (`@hust.edu.vn`) |
| Admin Auth | Static API Key in `X-Admin-Key` header | Role-based with proper identity provider |
| Prompt Injection | System prompt guardrails in `generate.py` | Dedicated input sanitizer middleware |
| CORS | Allow all origins (`*`) for MVP demo | Restrict to deployed frontend domain in production |
| Data Access | Read-only `/chat` routes; write-only `/admin` routes | Same, with token-scoped permissions |

**Route-level RBAC pattern (FastAPI dependency):**
```python
# Admin routes protected via header check
async def verify_admin(x_admin_key: str = Header(...)):
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
```

---

### API & Communication Patterns

**Base URL:** `/api/v1/`

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/v1/chat/query` | `POST` | None (MVP) | Stream answer via SSE |
| `/api/v1/admin/ingest` | `POST` | Admin Key | Upload doc, trigger ingest |
| `/api/v1/health` | `GET` | None | Liveness check |

**Request Schema — `/api/v1/chat/query`:**
```json
{
  "query": "Sinh viên K68 bị cảnh báo học tập khi nào?",
  "conversation_id": "optional-uuid"
}
```

**Response — Server-Sent Events (SSE) stream:**
```
data: {"type": "token", "content": "Theo"}
data: {"type": "token", "content": " Điều 10..."}
data: {"type": "citations", "sources": [...]}
data: {"type": "done"}
```

**Why SSE over WebSocket:** SSE is unidirectional (server → client), simpler to implement, works over plain HTTP/1.1, and is perfectly suited for LLM token streaming. WebSocket adds unnecessary complexity for this use case.

**Error Response Standard:**
```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Hệ thống đang bận. Tự động thử lại...",
    "retry_after": 16
  }
}
```

**Rate Limit & Resilience:**
- `429` from Gemini → exponential backoff in `generate.py` (already implemented, 3 retries)
- `503` on total failure → return structured error to frontend for graceful display (FR18)

---

### Frontend Architecture

**Technology:** Vanilla HTML5 + CSS3 + ES6 JavaScript (no build toolchain)

| Decision | Choice | Rationale |
|---|---|---|
| Rendering | Client-side DOM manipulation | Simple, no framework overhead |
| API Communication | `EventSource` API (native SSE) | Native browser SSE support, zero dependencies |
| Markdown Rendering | `marked.js` (CDN) | Renders LLM markdown responses, lightweight |
| State | In-memory JS object (session only) | MVP does not require persistence |
| Styling | Custom CSS with CSS Variables | Full control, Vietnamese font support |
| Font | `Inter` or `Roboto` from Google Fonts | Vietnamese character support confirmed |

**Served by:** FastAPI `StaticFiles` mount — no separate web server needed for MVP:
```python
app.mount("/", StaticFiles(directory="src/web", html=True), name="web")
```

---

### Infrastructure & Deployment

| Decision | MVP Choice | Rationale |
|---|---|---|
| Deployment Target | Local / single-server | Demo phase; no cloud infra required yet |
| Process Manager | `uvicorn` directly | Sufficient for demo load |
| Environment Config | `.env` via `python-dotenv` | Already established pattern |
| ChromaDB Storage | Local filesystem (`data/chroma_db/`) | NFR-R2 persistent; path configurable via env |
| Logging | Python `logging` module (stdout) | Simple, parseable, sufficient for MVP |
| Monitoring | None (MVP) | Deferred to Phase 2 |

**Launch Command:**
```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Decision Impact Analysis

**Implementation Sequence:**
1. Create `src/api/main.py` with FastAPI app, lifespan, CORS, StaticFiles
2. Implement `src/api/routes/chat.py` — SSE streaming endpoint wrapping `generate_answer()`
3. Implement `src/api/routes/admin.py` — stub ingest endpoint
4. Build `src/web/index.html` + `style.css` + `app.js` — Web Chat UI
5. Update `requirements.txt` with `fastapi`, `uvicorn[standard]`
6. Stub `src/api/routes/admin.py` for Phase 3 expansion

**Cross-Component Dependencies:**
- `chat.py` → imports `domain_rerank` from `test_retrieval.py` and `generate_answer` from `generate.py`
- `main.py` → owns ChromaDB client singleton; passes collection via `request.app.state`
- `app.js` → calls `/api/v1/chat/query` and renders SSE token stream in real time

---

## Implementation Patterns & Consistency Rules

### 1. ChromaDB Singleton Pattern
**Pattern:** The vector database client must be initialized EXACTLY ONCE at application startup.
**Implementation:** Use FastAPI's `@asynccontextmanager def lifespan(app: FastAPI):` to create the `PersistentClient` and store it in `app.state`.
**Why:** Re-instantiating `PersistentClient` per-request degrades performance and causes filesystem lock contention on Windows.

### 2. SSE Streaming Pattern
**Pattern:** LLM responses flow instantly from backend to frontend without waiting for the full generation.
**Implementation:** API routes must return FastAPI `StreamingResponse` with `media_type="text/event-stream"`. The generator function yields server-sent events serialized as JSON dictionaries:
- `data: {"type": "token", "content": "..."}\n\n`
- `data: {"type": "citations", "sources": [...]}\n\n`
- `data: {"type": "done"}\n\n`
- `data: {"type": "error", "message": "..."}\n\n`

### 3. Vietnamese Encoding Guard
**Pattern:** End-to-end UTF-8 transparency.
**Implementation:** All file `open()` calls, FastAPI responses, and frontend HTML meta tags MUST explicitly define `utf-8`. Furthermore, Chunker regexes matching Vietnamese markers (e.g., "CHƯƠNG") must strictly use `re.IGNORECASE` and handle trailing whitespace/punctuation gracefully using group alternatives like `(?:[:\.\s]|$)`.

### 4. Metadata Propagation Contract
**Pattern:** The structural provenance of every chunk is immutable.
**Implementation:** The `embed_and_store.py`, `test_retrieval.py`, and `generate.py` layers must strictly pass along the 8-field schema without mutation: `document`, `chapter`, `section`, `article`, `appendix`, `table_label`, `part`, `citation`. Dropping fields breaks the FR12 citation requirement.

### 5. Centralized Rate-Limit Resilience
**Pattern:** API rate limits (HTTP 429) from external LLM providers are handled closest to the source.
**Implementation:** Exponential backoff (max 3 retries) remains entirely self-contained within `generate.py::_call_gemini()`. FastAPI route handlers do NOT contain retry loops; they simply await the result or catch ultimate failures to yield an `error` SSE event.

### 6. Standardized Error Masking
**Pattern:** Internal traceback strings never leak to the frontend.
**Implementation:** FastAPI handlers catch pipeline exceptions and return them as structured JSON: `{"error": {"code": "...", "message": "friendly message in Vietnamese", "retry_after": X}}`.

---

## Project Structure & Boundaries

### Complete Project Directory Structure

```text
enterprise_rag_system/
├── requirements.txt            # Updated: fastapi, uvicorn, sse-starlette added
├── .env                        # GEMINI_API_KEY, GROQ_API_KEY, LLM_PROVIDER
├── data/
│   ├── raw/                    # Original DOCX/PDF files
│   ├── processed/              # corpus_chunks.json
│   └── chroma_db/              # Persistent ChromaDB storage
│
├── src/
│   ├── pipeline/               # [BOUNDARY: Core RAG Engine]
│   │   ├── chunker.py          # Structural parsing
│   │   ├── document_processor.py
│   │   ├── embed_and_store.py  # ChromaDB ingestion logic
│   │   ├── generate.py         # LLM Generation with Backoff
│   │   ├── ingest.py           # Pipeline entry point
│   │   └── test_retrieval.py   # Vector Retrieval + Domain Rerank
│   │
│   ├── api/                    # [BOUNDARY: REST/Streaming API Layer]
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI App, Lifespan, CORS, StaticFiles mount
│   │   ├── dependencies.py     # Auth & State helpers (e.g., get_chroma_client)
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── chat.py         # POST /api/v1/chat/query (SSE endpoint)
│   │       └── admin.py        # POST /api/v1/admin/ingest (Auth protected stub)
│   │
│   └── web/                    # [BOUNDARY: Frontend Client UI]
│       ├── index.html          # Web Chat Interface
│       ├── style.css           # Glassmorphic, modern Hust branding
│       └── app.js              # SSE client, Markdown rendering
```

### Architectural Boundaries

**API Boundaries:**
- The `src/api` module serves as the **only** entry point for network requests.
- Internal functions in `src/pipeline` must never instantiate their own network servers or database connections directly; they should accept the `chromadb.Collection` object passed down from the FastAPI `app.state`.

**Component Boundaries:**
- **Pipeline Layer:** Unaware of HTTP. It consumes Python dicts/strings and returns markdown strings/dicts. `print()` statements in pipeline scripts must be decoupled or converted to a structured `logging` module so they don’t spam stdout during API requests.
- **API Layer:** Handles all I/O parsing, schema validation (Pydantic), and chunk conversion to SSE strings.
- **Frontend Layer:** Render-only terminal. Contains zero domain logic. Its only job is passing user input to the API and faithfully rendering the streaming Markdown response.

### Requirements to Structure Mapping

**Epic: Chat Interface (MVP)**
- UI: `src/web/index.html`, `src/web/app.js` (FR1, FR2, FR5)
- Server Route: `src/api/routes/chat.py` (FR18, NFR-P1)
- Generator Core: `src/pipeline/generate.py` (FR10, FR11, FR12, FR17)
- Retrieval Core: `src/pipeline/test_retrieval.py` (FR6, FR8, FR9)

**Epic: Administration Dashboard (Phase 3)**
- Stub Route: `src/api/routes/admin.py` (FR13, FR14, FR15, FR16)
- File processing Core: `src/pipeline/chunker.py`, `src/pipeline/embed_and_store.py` (FR7, NFR-P3)

### Integration Points

**Internal Data Flow (Chat Query):**
1. User clicks send in `web/app.js`.
2. Browser initiates `POST` fetch holding an `EventSource` to `/api/v1/chat/query`.
3. `api/routes/chat.py` receives request, calls `pipeline/test_retrieval.py` passing the `app.state.collection`.
4. Reranked chunks are passed to `pipeline/generate.py`.
5. Tokens are yielded asynchronously and proxied directly back to formatting in `app.js`.

---

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**
FastAPI perfectly complements the existing `google-genai` and `chromadb` synchronous/asynchronous mix. SSE Streaming operates cleanly natively in FastAPI without overhead.

**Pattern Consistency:**
Implementation of the 8-field Metadata Contract restricts mutation, cleanly preserving cohort structures for the LLM citation generation.

**Structure Alignment:**
The isolation of `src/pipeline` ensures the core RAG logic handles domain tasks silently, leaving all request routing, rate-limit backoffs (HTTP 429), and SSE processing entirely clear. 

### Requirements Coverage Validation ✅

**Epic/Feature Coverage:**
- **MVP Web UI:** Covered via Vanilla static files served by FastAPI routing.
- **MVP Chat endpoint:** Covered via `/api/v1/chat/query` SSE handler.
- **Admin Dashboard (Phase 3):** Endpoint `/api/v1/admin/ingest` cleanly stubbed and RBAC logic (X-Admin-Key) defined.

**Functional Requirements Coverage:**
All 18 FRs are architecturally supported, explicitly mapped out from Generation (FR10-FR12 citations) to Admin resilience (FR18 structural error bubbling).

**Non-Functional Requirements Coverage:**
- **NFR-P1 (Speed):** Streaming API handles instant TTFT.
- **NFR-R2 (Persistence):** Local disk Chromadb PersistentClient mandated.
- **NFR-S2 (Read-only):** Strict endpoint segregation (Chat vs Admin routes).

### Implementation Readiness Validation ✅

**Decision Completeness:**
File locations, command bootstraps (uvicorn), and streaming patterns are specified.

**Structure Completeness:**
Boundaries mapped explicit files (e.g. `src/api/routes/chat.py`). Integration points explain how front-end triggers vector pipelines.

### Architecture Completeness Checklist

**✅ Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**✅ Architectural Decisions**
- [x] Critical decisions documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Performance considerations addressed

**✅ Implementation Patterns**
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified
- [x] Process patterns documented

**✅ Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High (Existing RAG codebase acts as a battle-tested engine).

**Key Strengths:**
Direct extension. No bloated third-party frameworks. Precise streaming output ensures student experience feels fast.

**Areas for Future Enhancement:**
In Phase 2, `app.js` vanilla JS UI will likely need migration to React/Next.js for complex chat history rendering.

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented
- Use implementation patterns consistently across all components
- Respect project structure and boundaries
- Refer to this document for all architectural questions

**First Implementation Priority:**
`mkdir -p src/api/routes src/web` and set up `src/api/main.py`.
