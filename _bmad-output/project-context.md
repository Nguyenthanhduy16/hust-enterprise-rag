---
project_name: 'enterprise_rag_system'
user_name: 'BOSS'
date: '2026-04-11'
sections_completed:
  ['technology_stack', 'language_rules', 'framework_rules', 'critical_rules']
status: 'complete'
rule_count: 9
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- Python
- PyMuPDF==1.24.0
- python-docx==1.1.0
- chromadb
- google-genai
- python-dotenv==1.0.1

## Critical Implementation Rules

### Language-Specific Rules

- **Type Hinting:** Strictly use modern Python type hints for function signatures (e.g., `text: str, part: str = "1/1" -> dict`).
- **Data Encapsulation:** Wrap complex logic inside static methods or classes where appropriate (e.g., `VietnameseRegulationCleaner`, `RegulationChunker`).
- **Environment Variables:** Expect API keys (`GEMINI_API_KEY`) to be managed via `python-dotenv` and loaded early in executable scripts.

### Domain-Specific Framework Rules (RAG)

- **Rate Limits & API Resilience:** When using `google-genai` for embeddings, strictly adhere to the "slow/safe" batching strategy (e.g., batches of 15, sleeping 20s between batches) with an automated retry loop for `429 Too Many Requests` to handle Gemini free-tier rate limits gracefully.
- **Structural Chunking over Fixed Window:** Do NOT chunk strictly by token length. Use semantic boundaries based on Vietnamese document headings (`Chương`, `Mục`, `Điều`, `Khoản`, `Phụ lục`) matching the internal `RegulationChunker` logic. 
- **ChromaDB Metadata:** Any interactions with ChromaDB must include or reference the standard metadata fields: `document`, `chapter`, `section`, `article`, `appendix`, `table_label`, `part`, and `citation`.

### Critical Don't-Miss Rules

- **Reranker Scoring Equations:** Modifying `test_retrieval.py` must preserve the additive `domain_rerank` formula. Keep foundational math stable: L2 conversions `1 / (1 + l2_dist)` and Domain Identifiers parsing (`doc_ids_in_query = set(re.findall(r'\b(k\d{2}|\d{4}-\d{4})\b', query_lower))`). Do NOT blindly replace keyword exact-matching overlaps without careful review.
- **Table Detection Spillover:** When modifying `chunker.py`, remember that "Bảng" (Table) tags only add `table_label` metadata and MUST NOT trigger a chunk structural boundary split. Appendices (`Phụ lục`) ARE structural boundaries and must reset the nested `article` context.
- **Regex Boundary Gotchas:** Vietnamese headings often end with or without trailing punctuation. Heading matching regexes must support end-of-line gracefully (e.g., `(?:[:\.\s]|$)`) to prevent swallowing "CHƯƠNG" segments in body text.

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-04-11
