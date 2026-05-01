import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from google import genai
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions

# class GeminiEmbeddingFunction(EmbeddingFunction):
#     def __init__(self, api_key: str, model_name: str = "models/gemini-embedding-001"):
#         self.client = genai.Client(api_key=api_key)
#         self.model_name = model_name
#         
#     def __call__(self, input: Documents) -> Embeddings:
#         cleaned_input = [text.replace("\n", " ").strip() for text in input]
#         response = self.client.models.embed_content(
#             model=self.model_name,
#             contents=cleaned_input,
#         )
#         return [e.values for e in response.embeddings]
    
load_dotenv()

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent

JSON_PATH = PROJECT_ROOT / "data" / "processed" / "corpus_chunks.json"
CHROMA_DB_DIR = PROJECT_ROOT / "data" / "chroma_db"

def store_chunks():
    if not JSON_PATH.exists():
        print(f"File not found: {JSON_PATH}")
        print("Please run ingest.py first to extract chunks.")
        return

    # api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    # if not api_key or "your_" in api_key:
    #     print("ERROR: Invalid or missing API KEY in your .env file.")
    #     return

    print("Loading chunks from JSON...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks.")

    print("Initializing local ChromaDB Client...")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))

    # gemini_ef = GeminiEmbeddingFunction(api_key=api_key)
    print("Loading local embedding model: truro7/vn-law-embedding...")
    law_embedding_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="truro7/vn-law-embedding"
    )

    collection = client.get_or_create_collection(
        name="hust_regulations_v2",
        embedding_function=law_embedding_ef
    )

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        ids.append(str(chunk["id"]))
        documents.append(chunk["content"])
        metadatas.append({
            "document":    str(chunk.get("document", "Unknown")),
            "chapter":     str(chunk.get("chapter", "")),
            "section":     str(chunk.get("section", "")),
            "article":     str(chunk.get("article", "")),
            "appendix":    str(chunk.get("appendix", "")),
            "table_label": str(chunk.get("table_label", "")),
            "part":        str(chunk.get("part", "1/1")),
            "citation":    str(chunk.get("citation", chunk.get("document", "Unknown"))),
        })

    # 6. Upsert data to ChromaDB in batches (Local model is fast, no need for small batches)
    batch_size = 500
    total_batches = (len(ids) + batch_size - 1) // batch_size

    print(f"Starting Vector Embedding & Syncing... (Total batches: {total_batches})")
    print("Using fast local embedding mode. Please wait...")

    i = 0
    while i < len(ids):
        end = i + batch_size
        batch_num = (i // batch_size) + 1
        
        try:
            collection.upsert(
                ids=ids[i:end],
                documents=documents[i:end],
                metadatas=metadatas[i:end]
            )
            print(f" -> Embedded & Upserted batch {batch_num}/{total_batches}")
            
            i += batch_size # Move to next batch only if successful
            
            # if i < len(ids):
            #     print(f"    Waiting 20s for quota reset...")
            #     time.sleep(20)
                
        except Exception as e:
            # if "429" in str(e) or "QUOTA" in str(e).upper():
            #     print(f"\n[QUOTA REACHED] Gemini says wait. Sleeping for 70 seconds before retrying batch {batch_num}...")
            #     time.sleep(70)
            # else:
            print(f"An unexpected error occurred: {e}")
            break # Stop on errors

    print("\nVector Sync Complete!")
    print(f"Your Local Vector Database is now populated at: {CHROMA_DB_DIR}")

if __name__ == "__main__":
    store_chunks()