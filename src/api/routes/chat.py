import asyncio
import json
import logging
import os
import re
import time
from typing import AsyncIterator

from openai import OpenAI
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.pipeline.test_retrieval import domain_rerank

router = APIRouter()
log = logging.getLogger(__name__)

# Use gpt-4o for answering (better multi-step reasoning), gpt-4o-mini for decomposition (fast & cheap)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")

# Whitelist of models the frontend may request
ALLOWED_MODELS = {
    "gpt-4o": {"label": "GPT-4o", "tier": "Premium"},
    "gpt-4o-mini": {"label": "GPT-4o Mini", "tier": "Fast"},
}

_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


class ChatQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(7, ge=1, le=20)
    fetch_k: int = Field(12, ge=1, le=40)
    decompose: bool = True
    model: str | None = Field(None, description="Override LLM model for answer generation")


SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên môn về các quy định và quy chế của Đại học Bách khoa Hà Nội (HUST).
Nhiệm vụ của bạn là giải đáp thắc mắc của sinh viên một cách chính xác, ngắn gọn và dễ hiểu.

TUÂN THỦ NGHIÊM NGẶT CÁC QUY TẮC SAU:
1. CHỈ TRẢ LỜI dựa trên thông tin được cung cấp trong phần [NGỮ CẢNH] bên dưới.
2. NẾU THÔNG TIN KHÔNG ĐỦ để trả lời, hãy nói rõ: "Dựa trên các quy định hiện tại, tôi không có đủ thông tin để trả lời câu hỏi này." TUYỆT ĐỐI KHÔNG bịa đặt thêm các luật lệ, quy định, hoặc giả định không có thật.
3. PHẢI CÓ TRÍCH DẪN cuối câu trả lời, sử dụng chính xác Nguồn (ví dụ: "Theo Nguồn 1: Quy chế đào tạo đại học, Chương I, Điều 5..."). Bạn có thể trích dẫn nhiều nguồn nếu cần.
4. Trình bày các thông tin rõ ràng, dùng bullet points nếu cần liệt kê. Trả lời bằng tiếng Việt.
5. ĐỌC HIỂU CỰC KỲ CHÍNH XÁC: Tuyệt đối không nhầm lẫn các khái niệm có vẻ giống nhau (ví dụ: "đăng ký học" khác hoàn toàn với "đăng ký xét tốt nghiệp").
6. TÍNH TOÁN THỜI GIAN CẨN THẬN: Nếu liên quan đến "thời gian học tối đa", bạn PHẢI phân tích cụ thể: Thời gian chuẩn của chương trình là bao nhiêu? Được phép chậm tiến độ tối đa bao nhiêu? (Cộng 2 con số này lại). Lưu ý: Thời gian tối đa của người học song bằng bị giới hạn bởi thời gian tối đa của chương trình thứ nhất.

QUY TRÌNH SUY LUẬN (BẮT BUỘC tuân theo cho mọi câu hỏi):
Bước 1 - PHÂN TÍCH CÂU HỎI: Xác định chính xác người dùng muốn biết gì.
         Liệt kê tất cả các số liệu, mốc thời gian, loại chương trình, hiện trạng học vụ.
Bước 2 - TRÍCH XUẤT QUY ĐỊNH: Đọc kỹ [NGỮ CẢNH]. Trích dẫn chính xác từng Điều, Khoản
         có ảnh hưởng (cho dù là cấm đoán hay điều kiện bắt buộc). CHÚ Ý CAO ĐỘ các câu chứa chữ "phải", "chỉ được", "cùng lúc", "muộn nhất". Không bỏ sót quy định liên đới.
Bước 3 - PHÂN TÍCH LOGIC & ĐỐI CHIẾU: 
         Thực hiện các phép toán (nếu có). 
         So sánh từng điều kiện của người hỏi với từng quy định đã trích xuất. Ghi rõ: VI PHẠM hay HỢP LỆ cho mỗi điều kiện. Đánh giá tính khả thi một cách khắt khe.
Bước 4 - KẾT LUẬN: Tổng hợp kết quả logic để đưa ra câu trả lời cuối
         cùng, rõ ràng, dứt khoát.

QUAN TRỌNG: Bạn PHẢI trình bày đầy đủ 4 bước trên trong câu trả lời để
sinh viên hiểu rõ logic suy luận. Đừng chỉ đưa ra kết luận mà không giải thích.
"""


def format_context(ranked_chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(ranked_chunks):
        meta = chunk.get("metadata", {})
        header = f"[Nguồn {i+1}: {meta.get('document', 'Tài liệu hệ thống')}]"
        details = [d for d in (meta.get("chapter"), meta.get("article"), meta.get("table_label")) if d]
        if details:
            header += f" ({', '.join(details)})"
        parts.append(f"{header}\n{chunk.get('content', '')}\n")
    return "\n".join(parts)


def build_citations(ranked_chunks: list[dict]) -> list[dict]:
    out = []
    for i, chunk in enumerate(ranked_chunks):
        meta = chunk.get("metadata", {})
        out.append({
            "index": i + 1,
            "document": meta.get("document", ""),
            "chapter": meta.get("chapter", ""),
            "section": meta.get("section", ""),
            "article": meta.get("article", ""),
            "appendix": meta.get("appendix", ""),
            "table_label": meta.get("table_label", ""),
            "part": meta.get("part", ""),
            "citation": meta.get("citation", ""),
            "score": chunk.get("score", 0.0),
        })
    return out


def decompose_query(query: str) -> list[str]:
    prompt = f"""Bạn là chuyên gia phân tích câu hỏi về quy chế đại học.
Phân tách câu hỏi sau thành các câu hỏi con đơn giản hơn (mỗi câu trên 1 dòng, tối đa 5 câu, bảo toàn mốc thời gian/con số, không giải thích):

Câu hỏi gốc: {query}"""
    t0 = time.perf_counter()
    try:
        print(f"[PERF] decompose_query STARTING...", flush=True)
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=FAST_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content
        subs = [ln.strip() for ln in text.strip().split("\n") if len(ln.strip()) > 10]
        if query not in subs:
            subs.insert(0, query)
        print(f"[PERF] decompose_query took {time.perf_counter() - t0:.2f}s => {len(subs)} sub-queries", flush=True)
        return subs[:5]
    except Exception as exc:
        print(f"[PERF] decompose_query FAILED after {time.perf_counter() - t0:.2f}s: {exc}", flush=True)
        return [query]


def multi_query_retrieve(collection, queries: list[str], rerank_query: str, n_per_query: int, final_top_k: int) -> list[dict]:
    t0 = time.perf_counter()
    print(f"[PERF] multi_query_retrieve STARTING ({len(queries)} queries)...", flush=True)
    seen = set()
    docs, metas, dists = [], [], []
    for q in queries:
        try:
            res = collection.query(query_texts=[q], n_results=n_per_query)
        except Exception:
            continue
        for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            h = hash(d[:200])
            if h in seen:
                continue
            seen.add(h)
            docs.append(d)
            metas.append(m)
            dists.append(dist)
    if not docs:
        print(f"[PERF] multi_query_retrieve returned 0 docs in {time.perf_counter() - t0:.2f}s", flush=True)
        return []
    merged = {"documents": [docs], "metadatas": [metas], "distances": [dists]}
    result = domain_rerank(rerank_query, merged, top_k=final_top_k)
    print(f"[PERF] multi_query_retrieve took {time.perf_counter() - t0:.2f}s ({len(queries)} queries, {len(docs)} unique docs)", flush=True)
    return result


async def stream_answer(request: Request, payload: ChatQuery) -> AsyncIterator[dict]:
    collection = request.app.state.collection
    # Resolve model: use payload override if allowed, else default
    chosen_model = payload.model if (payload.model and payload.model in ALLOWED_MODELS) else DEFAULT_MODEL

    loop = asyncio.get_event_loop()

    if payload.decompose:
        sub_queries = await loop.run_in_executor(None, decompose_query, payload.query)
    else:
        sub_queries = [payload.query]

    yield {"event": "message", "data": json.dumps({"type": "status", "stage": "retrieving", "sub_queries": sub_queries})}

    ranked = await loop.run_in_executor(
        None,
        multi_query_retrieve,
        collection,
        sub_queries,
        payload.query,
        payload.fetch_k,
        payload.top_k,
    )

    if not ranked:
        yield {"event": "message", "data": json.dumps({"type": "token", "text": "Dựa trên các quy định hiện tại, tôi không có đủ thông tin để trả lời câu hỏi này."})}
        yield {"event": "message", "data": json.dumps({"type": "citations", "citations": []})}
        yield {"event": "message", "data": json.dumps({"type": "done"})}
        return

    yield {"event": "message", "data": json.dumps({"type": "citations", "citations": build_citations(ranked)})}

    context = format_context(ranked)
    user_prompt = f"[NGỮ CẢNH]\n{context}\n\n[CÂU HỎI CỦA SINH VIÊN]\n{payload.query}\n\nHãy phân tích và trả lời câu hỏi trên theo quy trình suy luận 4 bước đã được hướng dẫn."

    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def producer():
        t0 = time.perf_counter()
        try:
            client = get_openai_client()
            print(f"[PERF] LLM stream STARTING (model={chosen_model})...", flush=True)
            stream = client.chat.completions.create(
                model=chosen_model,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    asyncio.run_coroutine_threadsafe(queue.put(("token", text)), loop)
            print(f"[PERF] LLM stream COMPLETED in {time.perf_counter() - t0:.2f}s", flush=True)
        except Exception as e:
            print(f"[PERF] LLM stream FAILED after {time.perf_counter() - t0:.2f}s: {e}", flush=True)
            asyncio.run_coroutine_threadsafe(queue.put(("error", str(e))), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put((None, SENTINEL)), loop)

    loop.run_in_executor(None, producer)

    while True:
        if await request.is_disconnected():
            break
        kind, payload_item = await queue.get()
        if payload_item is SENTINEL:
            break
        if kind == "token":
            yield {"event": "message", "data": json.dumps({"type": "token", "text": payload_item})}
        elif kind == "error":
            yield {"event": "message", "data": json.dumps({"type": "error", "message": payload_item})}
            break

    yield {"event": "message", "data": json.dumps({"type": "done"})}


@router.post("/query")
async def chat_query(payload: ChatQuery, request: Request):
    return EventSourceResponse(stream_answer(request, payload))


@router.post("/debug")
async def chat_debug(payload: ChatQuery, request: Request):
    """Debug endpoint exposing full reranker scoring breakdown for any query.
    No LLM generation is triggered (retrieval + scoring only).
    """
    collection = request.app.state.collection
    loop = asyncio.get_event_loop()

    t0 = time.perf_counter()
    if payload.decompose:
        sub_queries = await loop.run_in_executor(None, decompose_query, payload.query)
    else:
        sub_queries = [payload.query]
    
    t1 = time.perf_counter()

    ranked = await loop.run_in_executor(
        None,
        multi_query_retrieve,
        collection,
        sub_queries,
        payload.query,
        payload.fetch_k,
        payload.top_k,
    )
    t2 = time.perf_counter()

    return {
        "query": payload.query,
        "sub_queries": sub_queries,
        "scored_candidates": ranked,
        "timings": {
            "decompose_s": round(t1 - t0, 3),
            "retrieve_and_rerank_s": round(t2 - t1, 3),
            "total_s": round(t2 - t0, 3)
        }
    }


@router.get("/models")
async def list_models():
    """Return the list of models the frontend may choose from."""
    models = []
    for model_id, info in ALLOWED_MODELS.items():
        models.append({
            "id": model_id,
            "label": info["label"],
            "tier": info["tier"],
            "default": model_id == DEFAULT_MODEL,
        })
    return {"models": models}
