import os

# Must be set before importing sentence-transformers / numpy
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = PROJECT_ROOT / "src" / "pipeline"
WEB_DIR = PROJECT_ROOT / "src" / "web"

if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


load_dotenv(PROJECT_ROOT / ".env")

import chromadb
from chromadb.utils import embedding_functions

from src.api.routes import chat as chat_routes
from src.api.routes import admin as admin_routes

CHROMA_DB_DIR = PROJECT_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "hust_regulations_v2"
EMBEDDING_MODEL = "truro7/vn-law-embedding"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[startup] Loading embedding model: {EMBEDDING_MODEL}")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    print(f"[startup] Opening ChromaDB at {CHROMA_DB_DIR}")
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    collection = chroma_client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    print(f"[startup] Collection '{COLLECTION_NAME}' ready ({collection.count()} chunks)")

    app.state.chroma_client = chroma_client
    app.state.embedding_fn = embedding_fn
    app.state.collection = collection
    app.state.admin_key = os.getenv("ADMIN_KEY", "")

    yield

    print("[shutdown] Releasing ChromaDB client")
    app.state.chroma_client = None
    app.state.collection = None


app = FastAPI(
    title="HUST Regulation QA",
    description="RAG chatbot cho quy chế Đại học Bách khoa Hà Nội",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_routes.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(admin_routes.router, prefix="/api/v1/admin", tags=["admin"])


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "collection": COLLECTION_NAME,
        "count": app.state.collection.count() if getattr(app.state, "collection", None) else 0,
    }


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    # Chạy uvicorn từ bên trong code python
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
