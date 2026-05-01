---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish']
inputDocuments: ['_bmad-output/brainstorming/brainstorming-session-2026-04-11.md', '_bmad-output/project-context.md']
workflowType: 'prd'
briefCount: 0
researchCount: 0
brainstormingCount: 1
projectDocsCount: 1
classification:
  projectType: 'API-first RAG System with Web Chat Interface'
  domain: 'Vietnamese Administrative Regulations'
  complexity: 'Medium-to-High'
  projectContext: 'brownfield'
---

# Product Requirements Document - HUST Regulation QA

**Author:** BOSS
**Date:** 2026-04-11

## Executive Summary

HUST Regulation QA là hệ thống chatbot hỏi-đáp thông minh dành cho sinh viên và cán bộ Đại học Bách khoa Hà Nội. Hệ thống sử dụng kiến trúc Retrieval-Augmented Generation (RAG) để trả lời các câu hỏi về quy chế đào tạo, quy định học phí, chuẩn ngoại ngữ đầu ra, và các quy định hành chính khác — dựa hoàn toàn trên văn bản gốc có trích dẫn cụ thể đến từng Điều/Khoản. Đối tượng sử dụng chính là sinh viên các khóa (K68, K70,...) cần tra cứu nhanh các quy định áp dụng cho khóa học của mình mà không phải đọc toàn bộ văn bản pháp quy.

### What Makes This Special
- **Nhận diện cấu trúc văn bản hành chính Việt Nam:** Hệ thống phân tích tài liệu theo đúng hệ thống phân cấp Chương → Mục → Điều → Khoản → Phụ lục, thay vì cắt đoạn ngữ cảnh theo độ dài cố định như các hệ thống RAG thông thường.
- **Truy xuất theo khóa học cụ thể:** Khi sinh viên hỏi về quy định K68, hệ thống ưu tiên chính xác tài liệu áp dụng cho K68 và phạt điểm các tài liệu K70 không liên quan.
- **Từ chối trả lời khi không đủ căn cứ:** Thay vì bịa đặt quy định, hệ thống thông báo rõ ràng khi ngữ cảnh không đủ để trả lời, đảm bảo độ tin cậy.

### Project Classification
| Thuộc tính | Giá trị |
|---|---|
| Loại sản phẩm | API-first RAG System with Web Chat Interface |
| Lĩnh vực | Vietnamese Administrative Regulations |
| Độ phức tạp | Trung bình - Cao |
| Trạng thái | Brownfield (Pipeline Ingestion/Retrieval đã hoạt động) |

## Success Criteria & Measurable Outcomes

### User Success
- **Độ tin cậy tuyệt đối:** 100% câu trả lời đều có trích dẫn rõ ràng từ nguồn. Sinh viên không bao giờ nhận được câu trả lời dạng "hallucination".
- **Tiết kiệm thời gian:** Tìm thấy điều kiện tốt nghiệp, chuẩn ngoại ngữ đúng khóa của mình trong vòng chưa tới 5 giây.

### Business Success
- **Giảm tải hành chính:** Giảm 50% thời lượng Phòng Đào tạo phải trả lời các câu hỏi thủ tục định kỳ lặp lại.
- **Tỉ lệ chấp nhận (Adoption):** Phục vụ thành công ít nhất 1.000 lượt truy vấn tự động từ sinh viên trong tháng triển khai đầu tiên.

### Technical Success & Measurable Outcomes
- **Độ chính xác truy xuất:** Top-3 kết quả trả về từ Vector DB cộng với Domain Reranker đạt độ chính xác >95%.
- **Zero-Hallucination Rate:** 100% đối với các truy vấn liên quan đến học vụ.
- **Latency:** End-to-end Latency (Từ lúc hỏi đến lúc phát sinh câu trả lời LLM) < 8 giây/truy vấn.

## Project Scoping & Phased Roadmap

### MVP Strategy & Philosophy
**MVP Approach ("Problem-solving MVP"):** Tập trung hoàn toàn vào việc chứng minh độ chính xác của core engine RAG khi kết hợp ChromaDB và LLM. Thiết kế tập trung vào giao diện Chat trực diện và trả lời đúng luật, bỏ qua các feature rườm rà.
**Resource Requirements:** 1 Backend/AI Engineer, 1 Frontend Developer. Server host ChromaDB nội bộ.

### Phase 1: MVP Feature Set
- Document Ingestion Pipeline (Chunker nhận biết Chương/Điều).
- Vector Retrieval & Domain Reranker (Penalty/Boost hệ số K- cohort).
- API Layer với module Generation trả lời tiếng Việt chính xác dựa trên Context.
- Simple & beautiful Web Chat UI (Hỗ trợ mobile, markdown, hiển thị trích dẫn).

### Phase 2: Growth (Post-MVP)
- System Authentication (Đăng nhập SSO `@hust.edu.vn`).
- Context Retention (Lưu lịch sử conversation).
- Guardrails gợi ý người dùng bổ sung thông tin (VD hỏi lại "Bạn khóa bao nhiêu?").

### Phase 3: Vision (Expansion)
- Nâng cấp thành hệ thống RAG thời gian thực đồng bộ Cổng thông tin.
- Admin Dashboard nhập/xuất tài liệu cho non-technical staff.
- Thống kê insight người dùng.

## User Journeys

### 1. Primary User (Happy Path) - Tra cứu chuẩn đầu ra
- **User:** Linh, sinh viên K68.
- **Tình huống:** Muốn biết TOEIC nội bộ có xét tốt nghiệp được không.
- **Hành trình:** Vào Chat UI gõ câu hỏi. Hệ thống tự nhận diện cụm "K68", quét đến "Phụ lục II: Chuẩn ngoại ngữ K68". Hệ thống trả lời ngay "Không được" dựa theo đúng phụ lục đó. Linh tiết kiệm được nhiều giờ lục lọi PDF.

### 2. Primary User (Edge Case) - Thiếu ngữ cảnh
- **User:** Nam, sinh viên K70.
- **Tình huống:** Nam hỏi "Cảnh báo học tập bị đuổi học không?" nhưng không ghi khóa học.
- **Hành trình:** Thay vì truy xuất sai quy định K64, hệ thống hỏi lại: "Quy định xử lý học vụ có thể khác nhau giữa các khóa. Bạn vui lòng cho biết bạn là sinh viên khóa (K) mấy?". Sau khi Nam điền K70, hệ thống lock đúng văn bản và trả lời.

### 3. Admin/Operations - Cập nhật quy định
- **User:** Cô Hoa, giáo vụ.
- **Tình huống:** Có quy chế đào tạo 2026 mới ban hành.
- **Hành trình:** Cô upload DOCX lên Dashboard, gắn thẻ "áp dụng từ K70". Ingestion tool chạy ngầm cắt Chương/Điều và sync vào ChromaDB. Chatbot tự động biết kiến thức mới nhất.

## Domain Requirements & Innovations

### Compliance & Regulatory
- **Chính xác văn bản pháp quy:** Phải trích xuất tài liệu Đại học Bách khoa Hà Nội, tuyệt đối không dùng Pre-trained knowledge của LLM.
- **Tính thời điểm:** Khi quy chế mới ban hành có tính mâu thuẫn, hệ thống phải phân biệt được hiệu lực của văn bản.

### Technical Innovations
- **Structural-Aware Vietnamese Chunking:** Bóc tách và giữ phân cấp văn bản pháp quy (Chương > Mục > Điều > Khoản), giúp LLM không hiểu lầm context giới hạn của từng Khoản.
- **Cohort-Targeted Reranking:** Giải quyết điểm yếu Vector Similarity vì text quy chế K68/K70 giống nhau đến 90%.

### Risk Mitigation & Validation
- **Rủi ro Rate Limit:** Backend thiết lập `Retry-After` Queues. Giao diện hiển thị lỗi thân thiện (Graceful failures).
- **Rủi ro Định dạng Mới:** Hệ thống bóc tách metadata kiểm tra độ dài Token, cảnh báo nếu format văn bản quá bất thường.
- **Đối chiếu A/B Validation:** Bắt buộc UI hiển thị rõ trích dẫn (Nguồn) để sinh viên double-check văn bản gốc.

## Technical Architecture (API-First System)

### Endpoint Specifications
- **`POST /api/v1/chat/query`:** Input gồm `query_text`, `conversation_id`. Output trả về JSON chứa `answer` (markdown), `citations`, hỗ trợ SSE stream chữ.
- **`POST /api/v1/admin/ingest`:** Multipart form-data chứa file DOCX và metadata để update database.

### Authentication Model
- Backend và Web Server gọi nhau qua Static API Key nội bộ. Sinh viên chứng thực qua Oauth2 Google (`@hust.edu.vn`).

### Data Schemas & Errors
- 400 Bad Request (thiếu input), 429 Too Many Requests, 500/503 fallback cho lỗi model LLM.
- Data lưu File-based SQLite cho ChromaDB nên cần Persistent Volume an toàn.

## Functional Requirements

### Chat Interaction
- **FR1:** Sinh viên có thể gửi câu hỏi bằng văn bản tiếng Việt.
- **FR2:** Sinh viên có thể đọc câu trả lời do hệ thống tổng hợp.
- **FR3:** Sinh viên có thể xem các trích dẫn tài liệu gốc đính kèm cùng câu trả lời.
- **FR4:** Sinh viên có thể cung cấp thêm ngữ cảnh bổ sung khi hệ thống phát hiện thiếu thông tin.
- **FR5:** Sinh viên có thể xem lại bối cảnh các câu và trả lời trước đó trong cùng phiên chat.

### Retrieval & Context Architecture
- **FR6:** Hệ thống bóc tách và phân loại siêu dữ liệu cấu trúc (Chương, Mục, Điều) từ văn bản tiếng Việt.
- **FR7:** Hệ thống nhận diện và bảo toàn định dạng bảng biểu (Tables).
- **FR8:** Hệ thống ưu tiên (boost) kết quả tìm kiếm dựa trên từ khóa định danh khóa (K68, K70).
- **FR9:** Hệ thống tự động hạ điểm tham chiếu (penalize) của tài liệu thuộc khóa học không phù hợp.

### Generation & Guardrails
- **FR10:** Hệ thống tạo câu trả lời ngôn ngữ tự nhiên được "neo chặt" (grounded) vào tài liệu nội bộ.
- **FR11:** Hệ thống từ chối trả lời và thông báo rõ ràng khi thông tin truy xuất không đủ căn cứ.
- **FR12:** Hệ thống chèn các ID trích dẫn (citations) vào văn bản của câu trả lời.

### Knowledge Administration
- **FR13:** Admin tải lên phần quy chế dạng file DOCX, PDF.
- **FR14:** Admin gắn thẻ siêu dữ liệu (Năm ban hành, Áp dụng Khóa K).
- **FR15:** Admin kích hoạt tiến trình xử lý Ingest đưa văn bản vào Vector DB.
- **FR16:** Admin nhận cảnh báo hệ thống nếu một đoạn văn (chunk) bị cắt sai hoặc quá độ dài.

### Resilience
- **FR17:** Hệ thống tự động đẩy vào hàng đợi thử lại (retry) khi request gọi dịch vụ LLM bị từ chối do Rate Limit.
- **FR18:** Hệ thống gửi thông báo lỗi giao diện khi LLM hoặc Vector DB bị gián đoạn.

## Non-Functional Requirements

### Performance
- **NFR-P1 (Time-to-First-Token):** TTFT trên giao diện Chat UI không được vượt quá 3 giây.
- **NFR-P2 (End-to-End Latency):** Phản hồi hoàn chỉnh trong dưới 8 giây.
- **NFR-P3 (Ingestion Throughput):** Chunking và embedding 100 trang tài liệu dưới 3 phút.

### Security
- **NFR-S1 (Prompt Injection Defense):** Chặn hoàn toàn lệnh Jailbreak, chatbot tuyệt đối không trả lời nội dung ngoài lề.
- **NFR-S2 (Read-Only End-User):** Các Client API dùng bởi sinh viên chỉ có quyền truy xuất đọc (Read) ChromaDB. Mọi quyền Mutation cấp cho Admin.

### Reliability & Resilience
- **NFR-R1 (Rate-Limit Backoff):** Hệ thống tự động kích hoạt Exponential Backoff tối đa 3 lần khi lỗi HTTP 429.
- **NFR-R2 (Data Persistence):** Chạy ChromaDB trên Persistent Storage Volume, giữ ổn định data nếu server restart.
