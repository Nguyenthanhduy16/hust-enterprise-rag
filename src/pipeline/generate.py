import os
import time

# Fix OpenBLAS hanging/crashing issue when loading SentenceTransformers
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APIStatusError

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("Missing OPENAI_API_KEY in .env file. Please add it.")

client = OpenAI(api_key=openai_api_key)

DEFAULT_MODEL = "gpt-4o"
# DEFAULT_MODEL = "gpt-4o-mini"


def format_context(ranked_chunks: list[dict]) -> str:
    context_parts = []
    for i, chunk in enumerate(ranked_chunks):
        content = chunk.get("content", "")
        metadata = chunk.get("metadata", {})

        document = metadata.get("document", "Tài liệu hệ thống")
        chapter = metadata.get("chapter", "")
        article = metadata.get("article", "")
        table_label = metadata.get("table_label", "")

        source_header = f"[Nguồn {i+1}: {document}]"
        details = []
        if chapter:
            details.append(chapter)
        if article:
            details.append(article)
        if table_label:
            details.append(table_label)
        if details:
            source_header += f" ({', '.join(details)})"

        context_parts.append(f"{source_header}\n{content}\n")

    return "\n".join(context_parts)


def generate_answer(query: str, ranked_chunks: list[dict], model_name: str = DEFAULT_MODEL) -> str:
    if not ranked_chunks:
        return "Xin lỗi, tôi không tìm thấy tài liệu quy định nào liên quan để trả lời câu hỏi của bạn."

    formatted_context = format_context(ranked_chunks)

    system_instruction = """Bạn là trợ lý AI chuyên môn về các quy định và quy chế của Đại học Bách khoa Hà Nội (HUST).
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
sinh viên hiểu rõ logic suy luận. Đừng chỉ đưa ra kết luận mà không giải thích."""

    user_prompt = f"""[NGỮ CẢNH]
{formatted_context}

[CÂU HỎI CỦA SINH VIÊN]
{query}

Hãy phân tích và trả lời câu hỏi trên theo quy trình suy luận 4 bước đã được hướng dẫn."""

    max_retries = 3
    base_delay = 4

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )

            # Collect streamed tokens
            text_parts = []
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    text_parts.append(chunk.choices[0].delta.content)
            return "".join(text_parts)

        except RateLimitError as e:
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"⚠️ API bận hoặc bị giới hạn. Tự động thử lại sau {sleep_time} giây (Lần {attempt+1}/{max_retries-1})...")
                time.sleep(sleep_time)
                continue
            return f"Đã xảy ra lỗi khi kết nối với LLM: {e}"
        except APIStatusError as e:
            if e.status_code in (500, 502, 503) and attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"⚠️ Lỗi máy chủ. Tự động thử lại sau {sleep_time} giây...")
                time.sleep(sleep_time)
                continue
            return f"Đã xảy ra lỗi khi kết nối với LLM: {e}"
        except Exception as e:
            return f"Đã xảy ra lỗi khi kết nối với LLM: {e}"

    return "Đã xảy ra lỗi: Hệ thống AI đang bị quá tải. Vui lòng đợi một lát rồi thử lại."


# ---------------------------------------------------------------------------
# Interactive Testing Interface
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from pathlib import Path

    src_path = str(Path(__file__).parent.parent.parent)
    if src_path not in sys.path:
        sys.path.append(src_path)

    try:
        from src.pipeline.test_retrieval import test_retrieval, domain_rerank
        import chromadb
        from chromadb.utils import embedding_functions
        from src.pipeline.test_retrieval import CHROMA_DB_DIR

        def decompose_query(original_query: str) -> list[str]:
            decompose_prompt = f"""Bạn là chuyên gia phân tích câu hỏi về quy chế đại học.

Nhiệm vụ: Phân tách câu hỏi phức tạp dưới đây thành các câu hỏi con đơn giản hơn.
Mỗi câu hỏi con phải nhắm đến MỘT quy định/điều kiện cụ thể để dễ tra cứu.

Quy tắc BẮT BUỘC:
- Nếu câu hỏi có chứa MỐC THỜI GIAN (ví dụ: "tuần thứ 5", "năm 2") hoặc CON SỐ (ví dụ: "25 tín", "GPA 2.0"), phải BẢO TOÀN chính xác các mốc thời gian/con số này vào câu hỏi con tương ứng.
- Đảm bảo phải có câu hỏi con bao phủ mọi khía cạnh được hỏi (ví dụ: học phí, tín chỉ, trạng thái học vụ, thời gian tối đa...).
- Mỗi câu hỏi con trên 1 dòng riêng. Không đánh số, không gạch đầu dòng.
- Tối đa 5 câu hỏi con.
- CHỈ trả về các câu hỏi con, KHÔNG giải thích gì thêm.

Câu hỏi gốc: {original_query}"""

            try:
                response = client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    max_tokens=512,
                    messages=[{"role": "user", "content": decompose_prompt}],
                )
                text = response.choices[0].message.content
                sub_queries = [
                    line.strip() for line in text.strip().split('\n')
                    if line.strip() and len(line.strip()) > 10
                ]
                if original_query not in sub_queries:
                    sub_queries.insert(0, original_query)
                return sub_queries[:5]
            except Exception as e:
                print(f"  ⚠️ Decompose failed ({str(e)[:50]}), using original query.")
                return [original_query]

        def multi_query_retrieve(collection, queries: list[str], rerank_query: str, n_per_query: int = 10, final_top_k: int = 7) -> list[dict]:
            seen_ids = set()
            all_documents = []
            all_metadatas = []
            all_distances = []

            for q in queries:
                try:
                    results = collection.query(query_texts=[q], n_results=n_per_query)
                except Exception:
                    continue

                for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
                    doc_hash = hash(doc[:200])
                    if doc_hash not in seen_ids:
                        seen_ids.add(doc_hash)
                        all_documents.append(doc)
                        all_metadatas.append(meta)
                        all_distances.append(dist)

            if not all_documents:
                return []

            merged_results = {
                "documents": [all_documents],
                "metadatas": [all_metadatas],
                "distances": [all_distances],
            }
            return domain_rerank(rerank_query, merged_results, top_k=final_top_k)

        print("="*60)
        print(f"🤖 RAG CHATBOT - TRUY VẤN QUY CHẾ HUST")
        print(f"📡 LLM: OpenAI ({DEFAULT_MODEL})")
        print("Gõ 'exit' hoặc 'quit' để thoát.")
        print("="*60)

        print("⏳ Đang tải mô hình nhúng và kết nối cơ sở dữ liệu (Việc này có thể mất vài phút)...")
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        law_embedding_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="truro7/vn-law-embedding"
        )
        collection = chroma_client.get_collection(name="hust_regulations_v2", embedding_function=law_embedding_ef)
        print("✅ Tải xong! Bắt đầu nhập câu hỏi.")

        while True:
            test_q = input("\n📝 Nhập câu hỏi của bạn: ").strip()

            if test_q.lower() in ['exit', 'quit']:
                print("Tạm biệt!")
                break
            if not test_q:
                continue

            print("🔍 Đang phân tích câu hỏi...")
            sub_queries = decompose_query(test_q)
            if len(sub_queries) > 1:
                print(f"  📋 Đã tách thành {len(sub_queries)} câu truy vấn:")
                for i, sq in enumerate(sub_queries):
                    print(f"     {i+1}. {sq[:80]}...")

            print("📚 Đang truy xuất tài liệu từ nhiều góc độ...")
            ranked = multi_query_retrieve(collection, sub_queries, rerank_query=test_q, n_per_query=10, final_top_k=12)

            if not ranked:
                print("Không tìm thấy dữ liệu vector!")
                continue

            print(f"  ✅ Tìm được {len(ranked)} đoạn quy định liên quan.")
            print(f"🚀 ĐANG TẠO CÂU TRẢ LỜI TỪ LLM ({DEFAULT_MODEL})...")
            answer = generate_answer(test_q, ranked)
            print(f"\n{'-'*60}\n⚙️ TRẢ LỜI:\n{answer}\n{'-'*60}")

    except ImportError as e:
        print(f"Could not run integrated test due to import error outside expected project boundary: {e}")
