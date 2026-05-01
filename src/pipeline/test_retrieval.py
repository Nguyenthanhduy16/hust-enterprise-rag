import os
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from google import genai
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions
import re

load_dotenv()

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
CHROMA_DB_DIR = PROJECT_ROOT / "data" / "chroma_db"

# ---------------------------------------------------------------------------
# Embedding function (must match the one used in embed_and_store.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Domain-aware reranker for HUST regulations
# ---------------------------------------------------------------------------

# Maps query intent keywords → terms that should appear in relevant chunks
DOMAIN_BOOSTS = {
    "đăng ký":     ["đăng ký học tập", "đăng ký học phần", "đăng ký lớp", "điều chỉnh đăng ký"],
    "học phí":     ["học phí", "mức thu", "đóng phí", "nộp học phí", "tín chỉ"],
    "ngoại ngữ":  ["chuẩn ngoại ngữ", "tiếng anh", "ielts", "toeic", "vstep", "ngoại ngữ đầu ra"],
    "tốt nghiệp": ["điều kiện tốt nghiệp", "xét tốt nghiệp", "hạng tốt nghiệp", "đăng ký tốt nghiệp"],
    "cảnh báo":   ["cảnh báo học tập", "buộc thôi học", "kết quả học tập"],
    "chuyển ngành":["chuyển chương trình", "chuyển ngành", "chuyển hình thức"],
    "điểm":       ["điểm học phần", "điểm trung bình", "gpa", "cpa", "thang điểm"],
    "tín chỉ":    ["tín chỉ", "học phần", "tc tích lũy"],
    "nghỉ học":   ["nghỉ học tạm thời", "rút hồ sơ", "bảo lưu", "rút bớt"],
    "song bằng":  ["hai chương trình", "cùng lúc hai", "ctđt thứ hai", "chương trình thứ hai", "song bằng"],
    "thời gian":  ["thời gian tối đa", "thời gian đào tạo", "chậm tiến độ", "tiến độ chuẩn"],
}

# Queries about these topics benefit from table-containing chunks
TABLE_QUERY_HINTS = ["bảng", "quy đổi", "mức", "điểm", "học phí", "chứng chỉ", "ielts", "toeic"]

# Chunks with this article are usually low-value for substantive queries
PENALTY_ARTICLES = ["hiệu lực thi hành"]


def domain_rerank(query: str, results: dict, top_k: int) -> list[dict]:
    """
    Domain-aware reranker for HUST regulation retrieval.

    Score = 0.55 × vec_similarity
          + 0.25 × keyword_overlap
          + 0.20 × domain_boost
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())
    candidates = []

    distances  = results["distances"][0]
    metadatas  = results["metadatas"][0]
    documents  = results["documents"][0]

    # Detect if query wants table data
    wants_table = any(hint in query_lower for hint in TABLE_QUERY_HINTS)
    
    # Detect doc identifiers in query for exact boosting
    doc_ids_in_query = set(re.findall(r'\b(k\d{2}|\d{4}-\d{4})\b', query_lower))

    for i in range(len(documents)):
        # --- 1. Vector similarity (L2 → 0-1) ---
        l2_dist       = distances[i]
        vec_similarity = 1 / (1 + l2_dist)

        # --- 2. Keyword overlap ---
        doc_lower     = documents[i].lower()
        doc_words     = set(doc_lower.split())
        kw_overlap    = len(query_words & doc_words) / max(len(query_words), 1)

        # --- 3. Domain boost ---
        domain_score = 0.0
        matched_intents = 0
        for intent_key, boost_terms in DOMAIN_BOOSTS.items():
            if intent_key in query_lower:
                # Check how many boost terms appear in the chunk
                hits = sum(1 for term in boost_terms if term in doc_lower)
                if hits > 0:
                    domain_score += hits / len(boost_terms)
                    matched_intents += 1
        if matched_intents > 0:
            domain_score /= matched_intents  # normalize to 0-1

        # --- 4. Exact Document Identifier Boost ---
        meta = metadatas[i]
        doc_name_lower = meta.get("document", "").lower()
        id_boost = 0.0
        if doc_ids_in_query:
            for doc_id in doc_ids_in_query:
                # Give a high boost if the identifier is in the document name or chunk text
                if doc_id in doc_name_lower or doc_id in doc_lower:
                    id_boost += 1.0  
                else:
                    # Penalize chunks that do not belong to the requested cohort
                    id_boost -= 0.5 

        # --- 5. Table boost ---
        table_boost = 0.0
        if wants_table and (meta.get("table_label", "") or meta.get("appendix", "")):
            table_boost = 0.3

        # --- 6. Penalty for "hiệu lực thi hành" when query is substantive ---
        article = meta.get("article", "").lower()
        if any(pen in article for pen in PENALTY_ARTICLES):
            # Only penalize if query is NOT specifically about hiệu lực
            if "hiệu lực" not in query_lower:
                domain_score = max(domain_score - 0.4, 0.0)

        # --- 6. Exact Number / Time Boost ---
        # If the query mentions a specific number or time ("tuần 5", "50%"), boost chunks containing it.
        # This prevents the reranker from dropping crucial numeric cross-references.
        numbers_in_query = set(re.findall(r'\b(\d+)\b', query_lower))
        num_boost = 0.0
        if numbers_in_query:
            for num in numbers_in_query:
                if num in doc_lower:
                    num_boost += 0.2

        # --- Final score ---
        # Note: Vector and keywords are foundational. Domain, ID, Number, and Table boosts are additive.
        final_score = (0.50 * vec_similarity) + (0.25 * kw_overlap) + (0.15 * domain_score) + (0.1 * id_boost) + table_boost + num_boost

        candidates.append({
            "rank":         i + 1,
            "score":        round(final_score, 4),
            "vec_sim":      round(vec_similarity, 4),
            "kw_overlap":   round(kw_overlap, 4),
            "domain_boost": round(domain_score, 4),
            "id_boost":     round(id_boost, 4),
            "table_boost":  round(table_boost, 4),
            "num_boost":    round(num_boost, 4),
            "metadata":     meta,
            "content":      documents[i],
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]


# ---------------------------------------------------------------------------
# Retrieval + display
# ---------------------------------------------------------------------------

def test_retrieval(query_text: str, top_k: int = 3, fetch_k: int = 10):
    """
    Retrieves `fetch_k` candidates from ChromaDB, reranks them with the
    simple keyword reranker, and displays the top `top_k` results.

    Args:
        query_text: The user question.
        top_k:      Number of results to display after reranking.
        fetch_k:    How many raw candidates to pull from the vector DB
                    (should be > top_k so reranking has room to work).
    """
    # api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    # if not api_key:
    #     print("ERROR: No API key found. Set GEMINI_API_KEY in your .env file.")
    #     return

    # --- Connect to local ChromaDB ---
    client    = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    # gemini_ef = GeminiEmbeddingFunction(api_key=api_key)
    law_embedding_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="truro7/vn-law-embedding"
    )

    try:
        collection = client.get_collection(
            name="hust_regulations_v2",
            embedding_function=law_embedding_ef
        )
    except Exception:
        print("ERROR: Collection 'hust_regulations_v2' not found. Run embed_and_store.py first.")
        return

    print(f"\n{'='*58}")
    print(f"🔍 QUERY: {query_text}")
    print(f"{'='*58}\n")

    # --- Vector search (fetch more than needed for reranker) ---
    raw_results = collection.query(
        query_texts=[query_text],
        n_results=min(fetch_k, collection.count()),
    )

    if not raw_results["documents"][0]:
        print("No chunks found in the vector store.")
        return

    # --- Rerank with domain awareness ---
    ranked = domain_rerank(query_text, raw_results, top_k=top_k)

    # --- Display ---
    for i, hit in enumerate(ranked):
        meta     = hit["metadata"]
        citation = meta.get("citation") or meta.get("document", "Unknown")
        article  = meta.get("article", "")
        part     = meta.get("part", "")
        table    = meta.get("table_label", "")
        score    = hit["score"]
        vec_sim  = hit["vec_sim"]
        kw       = hit["kw_overlap"]
        domain   = hit["domain_boost"]
        id_bst   = hit.get("id_boost", 0.0)

        print(f"[RESULT {i+1}]  Score: {score}  (vec={vec_sim}, kw={kw}, domain={domain}, id_boost={id_bst})")
        print(f"📎 CITATION : {citation}")
        if article:
            print(f"   Article   : {article}  (part {part})")
        if table:
            print(f"   Table     : {table}")

        content = hit["content"]
        preview = content if len(content) < 700 else content[:700] + "\n… [TRUNCATED]"
        print(f"\n{preview}")
        print("-" * 58 + "\n")

    # Retrieval quality summary
    print(f"ℹ️  Retrieved {len(raw_results['documents'][0])} candidates → domain reranked → showing top {top_k}.\n")


# ---------------------------------------------------------------------------
# Test queries
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    queries = [
        "Sinh viên muốn đăng ký học phần thì cần đáp ứng những điều kiện gì?",
        "Chuẩn đầu ra ngoại ngữ của sinh viên K68 chính quy là gì?",
        "Mức học phí của chương trình chuẩn năm học 2025-2026 là bao nhiêu?",
    ]

    for q in queries:
        test_retrieval(query_text=q, top_k=3, fetch_k=10)
