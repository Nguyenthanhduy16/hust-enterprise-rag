"""
RAG Evaluation Pipeline for HUST Regulations System.

Measures quality across 3 stages:
  1. RETRIEVAL  – Are we finding the right chunks?
  2. RERANKING  – Does domain_rerank improve ordering?
  3. GENERATION – Is the final answer faithful and complete?

Usage:
    python evaluate_rag.py                  # Run full evaluation
    python evaluate_rag.py --stage retrieval  # Run only retrieval metrics
"""

import os
import sys
import json
import time
import re
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from collections import defaultdict

# Fix OpenBLAS issue
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
CHROMA_DB_DIR = PROJECT_ROOT / "data" / "chroma_db"
EVAL_OUTPUT_DIR = PROJECT_ROOT / "data" / "eval_results"

# ---------------------------------------------------------------------------
# Ground-truth test set  (query → expected relevant articles/citations)
# Extend this list with more cases for better coverage.
# ---------------------------------------------------------------------------

EVAL_DATASET = [
    {
        "id": "Q1",
        "query": "Sinh viên muốn đăng ký học phần thì cần đáp ứng những điều kiện gì?",
        "expected_articles": ["Điều 7", "Điều 8"],
        "expected_keywords": ["đăng ký", "học phần", "điều kiện"],
        "category": "đăng ký",
    },
    {
        "id": "Q2",
        "query": "Chuẩn đầu ra ngoại ngữ của sinh viên K68 chính quy là gì?",
        "expected_articles": ["Điều 27", "Điều 28"],
        "expected_keywords": ["ngoại ngữ", "chuẩn đầu ra", "K68"],
        "category": "ngoại ngữ",
    },
    {
        "id": "Q3",
        "query": "Mức học phí của chương trình chuẩn năm học 2025-2026 là bao nhiêu?",
        "expected_articles": [],
        "expected_keywords": ["học phí", "mức thu", "2025-2026"],
        "category": "học phí",
    },
    {
        "id": "Q4",
        "query": "Điều kiện để được xét tốt nghiệp là gì?",
        "expected_articles": ["Điều 27"],
        "expected_keywords": ["tốt nghiệp", "điều kiện", "xét"],
        "category": "tốt nghiệp",
    },
    {
        "id": "Q5",
        "query": "Sinh viên bị cảnh báo học tập trong trường hợp nào?",
        "expected_articles": ["Điều 15"],
        "expected_keywords": ["cảnh báo", "học tập", "kết quả"],
        "category": "cảnh báo",
    },
    {
        "id": "Q6",
        "query": "Thời gian đào tạo tối đa của chương trình chuẩn là bao lâu?",
        "expected_articles": ["Điều 4", "Điều 5"],
        "expected_keywords": ["thời gian", "tối đa", "đào tạo"],
        "category": "thời gian",
    },
    {
        "id": "Q7",
        "query": "Quy định về việc chuyển ngành hoặc chuyển chương trình đào tạo?",
        "expected_articles": ["Điều 19", "Điều 20"],
        "expected_keywords": ["chuyển ngành", "chuyển chương trình"],
        "category": "chuyển ngành",
    },
    {
        "id": "Q8",
        "query": "Cách tính điểm trung bình tích lũy (CPA) như thế nào?",
        "expected_articles": ["Điều 13", "Điều 14"],
        "expected_keywords": ["điểm", "trung bình", "tích lũy", "CPA"],
        "category": "điểm",
    },
]


# ---------------------------------------------------------------------------
# Metric data classes
# ---------------------------------------------------------------------------

@dataclass
class RetrievalMetrics:
    """Per-query retrieval quality."""
    query_id: str = ""
    query: str = ""
    # Core IR metrics
    hit_at_1: float = 0.0     # Was top-1 result relevant?
    hit_at_3: float = 0.0     # Any relevant in top 3?
    hit_at_5: float = 0.0     # Any relevant in top 5?
    mrr: float = 0.0          # Mean Reciprocal Rank
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    keyword_coverage: float = 0.0   # % expected keywords found in results
    avg_vec_similarity: float = 0.0
    num_candidates: int = 0


@dataclass
class RerankMetrics:
    """Measures reranker lift vs raw vector order."""
    query_id: str = ""
    raw_top1_relevant: bool = False
    reranked_top1_relevant: bool = False
    raw_mrr: float = 0.0
    reranked_mrr: float = 0.0
    mrr_lift: float = 0.0       # reranked_mrr - raw_mrr
    ndcg_at_3: float = 0.0


@dataclass
class GenerationMetrics:
    """Per-query generation quality (LLM-as-judge)."""
    query_id: str = ""
    faithfulness: float = 0.0    # 0-1: answer supported by context?
    completeness: float = 0.0    # 0-1: covers all aspects of question?
    has_citation: bool = False   # Did LLM cite sources?
    answer_length: int = 0
    latency_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Helper: check if a chunk is relevant to the expected articles
# ---------------------------------------------------------------------------

def is_relevant(chunk_meta: dict, chunk_content: str, expected_articles: list[str], expected_keywords: list[str]) -> bool:
    """A chunk is relevant if it matches an expected article OR covers enough keywords."""
    article = chunk_meta.get("article", "").lower()
    content_lower = chunk_content.lower()

    # Check article match
    for exp_art in expected_articles:
        if exp_art.lower() in article:
            return True

    # Fallback: keyword coverage >= 60%
    if expected_keywords:
        hits = sum(1 for kw in expected_keywords if kw.lower() in content_lower)
        if hits / len(expected_keywords) >= 0.6:
            return True

    return False


def compute_mrr(relevance_flags: list[bool]) -> float:
    """Compute Mean Reciprocal Rank from ordered relevance list."""
    for i, rel in enumerate(relevance_flags):
        if rel:
            return 1.0 / (i + 1)
    return 0.0


def compute_ndcg(relevance_flags: list[bool], k: int = 3) -> float:
    """Compute NDCG@k from binary relevance."""
    import math
    dcg = sum((1.0 if relevance_flags[i] else 0.0) / math.log2(i + 2)
              for i in range(min(k, len(relevance_flags))))
    # Ideal: all relevant at top
    ideal_count = min(sum(relevance_flags), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Stage 1: Retrieval Evaluation
# ---------------------------------------------------------------------------

def evaluate_retrieval(collection, eval_data: list[dict], fetch_k: int = 10) -> list[RetrievalMetrics]:
    """Evaluate raw vector retrieval (before reranking)."""
    print("\n" + "=" * 60)
    print("📊 STAGE 1: RETRIEVAL EVALUATION")
    print("=" * 60)

    results = []
    for item in eval_data:
        qid = item["id"]
        query = item["query"]
        expected_arts = item["expected_articles"]
        expected_kws = item["expected_keywords"]

        raw = collection.query(
            query_texts=[query],
            n_results=min(fetch_k, collection.count()),
        )

        docs = raw["documents"][0]
        metas = raw["metadatas"][0]
        dists = raw["distances"][0]

        # Compute relevance per position
        relevance = [
            is_relevant(metas[i], docs[i], expected_arts, expected_kws)
            for i in range(len(docs))
        ]

        # Keyword coverage in top-5 results
        top5_text = " ".join(docs[:5]).lower()
        kw_hits = sum(1 for kw in expected_kws if kw.lower() in top5_text)
        kw_coverage = kw_hits / len(expected_kws) if expected_kws else 0.0

        # Vector similarity (L2 → normalized)
        avg_sim = sum(1 / (1 + d) for d in dists[:5]) / min(5, len(dists)) if dists else 0.0

        m = RetrievalMetrics(
            query_id=qid,
            query=query,
            hit_at_1=1.0 if relevance and relevance[0] else 0.0,
            hit_at_3=1.0 if any(relevance[:3]) else 0.0,
            hit_at_5=1.0 if any(relevance[:5]) else 0.0,
            mrr=compute_mrr(relevance),
            precision_at_3=sum(relevance[:3]) / 3,
            precision_at_5=sum(relevance[:5]) / 5,
            keyword_coverage=round(kw_coverage, 3),
            avg_vec_similarity=round(avg_sim, 4),
            num_candidates=len(docs),
        )
        results.append(m)

        status = "✅" if m.hit_at_3 else "❌"
        print(f"  {status} [{qid}] Hit@3={m.hit_at_3:.0f}  MRR={m.mrr:.3f}  P@3={m.precision_at_3:.3f}  KW={m.keyword_coverage:.2f}  | {query[:50]}...")

    return results


# ---------------------------------------------------------------------------
# Stage 2: Reranking Evaluation
# ---------------------------------------------------------------------------

def evaluate_reranking(collection, eval_data: list[dict], fetch_k: int = 10, top_k: int = 5) -> list[RerankMetrics]:
    """Compare raw vector order vs domain_rerank order."""
    from test_retrieval import domain_rerank

    print("\n" + "=" * 60)
    print("📊 STAGE 2: RERANKING EVALUATION")
    print("=" * 60)

    results = []
    for item in eval_data:
        qid = item["id"]
        query = item["query"]
        expected_arts = item["expected_articles"]
        expected_kws = item["expected_keywords"]

        raw = collection.query(
            query_texts=[query],
            n_results=min(fetch_k, collection.count()),
        )

        docs = raw["documents"][0]
        metas = raw["metadatas"][0]

        # Raw order relevance
        raw_relevance = [
            is_relevant(metas[i], docs[i], expected_arts, expected_kws)
            for i in range(len(docs))
        ]

        # Reranked order relevance
        ranked = domain_rerank(query, raw, top_k=top_k)
        reranked_relevance = [
            is_relevant(r["metadata"], r["content"], expected_arts, expected_kws)
            for r in ranked
        ]

        raw_mrr = compute_mrr(raw_relevance)
        reranked_mrr = compute_mrr(reranked_relevance)

        m = RerankMetrics(
            query_id=qid,
            raw_top1_relevant=raw_relevance[0] if raw_relevance else False,
            reranked_top1_relevant=reranked_relevance[0] if reranked_relevance else False,
            raw_mrr=round(raw_mrr, 4),
            reranked_mrr=round(reranked_mrr, 4),
            mrr_lift=round(reranked_mrr - raw_mrr, 4),
            ndcg_at_3=round(compute_ndcg(reranked_relevance, k=3), 4),
        )
        results.append(m)

        arrow = "⬆️" if m.mrr_lift > 0 else ("➡️" if m.mrr_lift == 0 else "⬇️")
        print(f"  {arrow} [{qid}] Raw MRR={m.raw_mrr:.3f} → Reranked MRR={m.reranked_mrr:.3f} (lift={m.mrr_lift:+.3f})  NDCG@3={m.ndcg_at_3:.3f}")

    return results


# ---------------------------------------------------------------------------
# Stage 3: Generation Evaluation (LLM-as-Judge)
# ---------------------------------------------------------------------------

def evaluate_generation(collection, eval_data: list[dict], model_name: str = "gpt-4o-mini") -> list[GenerationMetrics]:
    """Generate answers and score them with LLM-as-judge."""
    from test_retrieval import domain_rerank
    from generate import generate_answer, format_context

    from openai import OpenAI
    judge_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    print("\n" + "=" * 60)
    print("📊 STAGE 3: GENERATION EVALUATION (LLM-as-Judge)")
    print("=" * 60)

    results = []
    for item in eval_data:
        qid = item["id"]
        query = item["query"]

        # Retrieve + rerank
        raw = collection.query(query_texts=[query], n_results=min(10, collection.count()))
        ranked = domain_rerank(query, raw, top_k=7)

        if not ranked:
            results.append(GenerationMetrics(query_id=qid))
            print(f"  ❌ [{qid}] No chunks retrieved, skipping generation.")
            continue

        context_text = format_context(ranked)

        # Generate answer
        t0 = time.time()
        answer = generate_answer(query, ranked, model_name=model_name)
        latency = time.time() - t0

        # Check citation presence
        has_citation = bool(re.search(r'[Nn]guồn\s*\d', answer))

        # LLM-as-Judge scoring
        judge_prompt = f"""Bạn là người đánh giá chất lượng câu trả lời của hệ thống RAG.

[NGỮ CẢNH ĐƯỢC CUNG CẤP CHO HỆ THỐNG]
{context_text[:3000]}

[CÂU HỎI]
{query}

[CÂU TRẢ LỜI CỦA HỆ THỐNG]
{answer[:3000]}

Đánh giá theo 2 tiêu chí (cho điểm 0.0 đến 1.0):

1. faithfulness: Câu trả lời có hoàn toàn dựa trên ngữ cảnh không? (1.0 = hoàn toàn trung thực, 0.0 = bịa đặt nhiều)
2. completeness: Câu trả lời có đầy đủ thông tin để giải đáp câu hỏi không? (1.0 = đầy đủ, 0.0 = thiếu nhiều)

Trả lời ĐÚNG format JSON (không giải thích):
{{"faithfulness": <float>, "completeness": <float>}}"""

        try:
            judge_resp = judge_client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=100,
                messages=[{"role": "user", "content": judge_prompt}],
            )
            scores = json.loads(judge_resp.choices[0].message.content.strip())
            faith = float(scores.get("faithfulness", 0))
            compl = float(scores.get("completeness", 0))
        except Exception as e:
            print(f"    ⚠️ Judge failed for {qid}: {e}")
            faith, compl = 0.0, 0.0

        m = GenerationMetrics(
            query_id=qid,
            faithfulness=round(faith, 2),
            completeness=round(compl, 2),
            has_citation=has_citation,
            answer_length=len(answer),
            latency_seconds=round(latency, 2),
        )
        results.append(m)

        cite_icon = "📎" if has_citation else "⚠️"
        print(f"  {cite_icon} [{qid}] Faith={m.faithfulness:.2f}  Compl={m.completeness:.2f}  Len={m.answer_length}  T={m.latency_seconds:.1f}s")

    return results


# ---------------------------------------------------------------------------
# Aggregate & report
# ---------------------------------------------------------------------------

def aggregate_report(ret_metrics, rerank_metrics, gen_metrics):
    """Print summary table and save JSON."""
    print("\n" + "=" * 60)
    print("📋 AGGREGATE SUMMARY")
    print("=" * 60)

    if ret_metrics:
        n = len(ret_metrics)
        avg_hit1 = sum(m.hit_at_1 for m in ret_metrics) / n
        avg_hit3 = sum(m.hit_at_3 for m in ret_metrics) / n
        avg_mrr  = sum(m.mrr for m in ret_metrics) / n
        avg_p3   = sum(m.precision_at_3 for m in ret_metrics) / n
        avg_kw   = sum(m.keyword_coverage for m in ret_metrics) / n

        print(f"\n  RETRIEVAL (n={n}):")
        print(f"    Hit@1        = {avg_hit1:.3f}")
        print(f"    Hit@3        = {avg_hit3:.3f}")
        print(f"    MRR          = {avg_mrr:.3f}")
        print(f"    Precision@3  = {avg_p3:.3f}")
        print(f"    Keyword Cov. = {avg_kw:.3f}")

    if rerank_metrics:
        n = len(rerank_metrics)
        avg_lift = sum(m.mrr_lift for m in rerank_metrics) / n
        avg_ndcg = sum(m.ndcg_at_3 for m in rerank_metrics) / n
        lift_positive = sum(1 for m in rerank_metrics if m.mrr_lift > 0)

        print(f"\n  RERANKING (n={n}):")
        print(f"    Avg MRR Lift = {avg_lift:+.3f}")
        print(f"    Avg NDCG@3   = {avg_ndcg:.3f}")
        print(f"    Queries improved = {lift_positive}/{n}")

    # Defaults for focus area checks
    avg_mrr = avg_kw = avg_lift = avg_faith = avg_compl = cite_rate = 1.0
    if ret_metrics:
        avg_mrr = sum(m.mrr for m in ret_metrics) / len(ret_metrics)
        avg_kw = sum(m.keyword_coverage for m in ret_metrics) / len(ret_metrics)
    if rerank_metrics:
        avg_lift = sum(m.mrr_lift for m in rerank_metrics) / len(rerank_metrics)

    if gen_metrics:
        ng = len(gen_metrics)
        avg_faith = sum(m.faithfulness for m in gen_metrics) / ng
        avg_compl = sum(m.completeness for m in gen_metrics) / ng
        cite_rate = sum(1 for m in gen_metrics if m.has_citation) / ng
        avg_lat   = sum(m.latency_seconds for m in gen_metrics) / ng

        print(f"\n  GENERATION (n={ng}):")
        print(f"    Faithfulness   = {avg_faith:.3f}")
        print(f"    Completeness   = {avg_compl:.3f}")
        print(f"    Citation Rate  = {cite_rate:.1%}")
        print(f"    Avg Latency    = {avg_lat:.1f}s")

    # Identify weakest areas
    print(f"\n  💡 RECOMMENDED FOCUS AREAS:")
    if ret_metrics and avg_mrr < 0.6:
        print(f"    ⚠️  Retrieval MRR is low ({avg_mrr:.3f}). Consider: better chunking, embedding model tuning, or hybrid search.")
    if ret_metrics and avg_kw < 0.5:
        print(f"    ⚠️  Keyword coverage is low ({avg_kw:.3f}). Add BM25 hybrid retrieval or expand chunks.")
    if rerank_metrics and avg_lift < 0:
        print(f"    ⚠️  Reranker is hurting MRR. Review domain boost weights or disable reranking.")
    if gen_metrics and avg_faith < 0.7:
        print(f"    ⚠️  Faithfulness is low ({avg_faith:.3f}). Strengthen grounding prompts or reduce context noise.")
    if gen_metrics and avg_compl < 0.7:
        print(f"    ⚠️  Completeness is low ({avg_compl:.3f}). Increase top_k or improve retrieval recall.")
    if gen_metrics and cite_rate < 0.8:
        print(f"    ⚠️  Citation rate is low ({cite_rate:.1%}). Enforce citation in system prompt.")

    if ret_metrics and avg_mrr >= 0.6 and (not gen_metrics or avg_faith >= 0.7):
        print(f"    ✅  Overall quality looks solid!")

    # Save results
    EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "retrieval": [asdict(m) for m in ret_metrics] if ret_metrics else [],
        "reranking": [asdict(m) for m in rerank_metrics] if rerank_metrics else [],
        "generation": [asdict(m) for m in gen_metrics] if gen_metrics else [],
    }
    out_path = EVAL_OUTPUT_DIR / f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  📁 Full report saved to: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate RAG pipeline quality")
    parser.add_argument("--stage", choices=["retrieval", "reranking", "generation", "all"], default="all",
                        help="Which stage(s) to evaluate")
    parser.add_argument("--fetch-k", type=int, default=10, help="Number of raw candidates to fetch")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LLM model for generation eval")
    args = parser.parse_args()

    # Load embedding model & collection
    import chromadb
    from chromadb.utils import embedding_functions

    print("⏳ Loading embedding model and ChromaDB...")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    law_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="truro7/vn-law-embedding"
    )

    try:
        collection = client.get_collection(name="hust_regulations_v2", embedding_function=law_ef)
    except Exception:
        print("❌ Collection 'hust_regulations_v2' not found. Run embed_and_store.py first.")
        return

    print(f"✅ Collection loaded: {collection.count()} chunks")

    ret_metrics = []
    rerank_metrics = []
    gen_metrics = []

    if args.stage in ("retrieval", "all"):
        ret_metrics = evaluate_retrieval(collection, EVAL_DATASET, fetch_k=args.fetch_k)

    if args.stage in ("reranking", "all"):
        rerank_metrics = evaluate_reranking(collection, EVAL_DATASET, fetch_k=args.fetch_k)

    if args.stage in ("generation", "all"):
        gen_metrics = evaluate_generation(collection, EVAL_DATASET, model_name=args.model)

    aggregate_report(ret_metrics, rerank_metrics, gen_metrics)


if __name__ == "__main__":
    main()
