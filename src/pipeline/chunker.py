import re
import uuid

# ---------------------------------------------------------------------------
# Text Cleaner
# ---------------------------------------------------------------------------

class VietnameseRegulationCleaner:
    """
    Cleans raw PDF-extracted text from Vietnamese administrative documents.
    Removes noise such as page numbers, dot leaders, headers/footers, and
    table artifacts that degrade embedding & retrieval quality.
    """

    # Patterns for common PDF noise
    PAGE_NUMBER_RE = re.compile(r'^\s*-?\s*\d{1,4}\s*-?\s*$')                      # standalone page numbers: "- 5 -", "12"
    DOT_LEADER_RE = re.compile(r'[.]{4,}')                                           # ........ (table of contents leaders)
    FOOTER_HEADER_RE = re.compile(r'^(Trang|Page)\s*\d+', re.IGNORECASE)            # "Trang 5", "Page 5"
    REPEATED_SEPARATOR_RE = re.compile(r'^[-_=]{3,}$')                               # --- or ===== separators
    SHORT_NOISE_RE = re.compile(r'^.{1,3}$')                                        # lines with ≤3 chars (e.g., dash, letter)
    CELL_SEPARATOR_RE = re.compile(r'^\|[-|]+\|$')                                   # markdown-style table separators
    MULTIPLE_SPACES_RE = re.compile(r'[ \t]{2,}')                                    # multiple spaces/tabs → single space

    def is_noise_line(self, line: str) -> bool:
        """Returns True if the line should be completely dropped."""
        s = line.strip()
        if not s:
            return True
        if self.PAGE_NUMBER_RE.match(s):
            return True
        if self.FOOTER_HEADER_RE.match(s):
            return True
        if self.REPEATED_SEPARATOR_RE.match(s):
            return True
        if self.CELL_SEPARATOR_RE.match(s):
            return True
        if self.SHORT_NOISE_RE.match(s) and not s.isdigit():
            # Very short non-digit lines are usually header/footer fragments
            return True
        return False

    def clean_line(self, line: str) -> str:
        """Cleans an individual line while preserving meaning."""
        # Remove dot leaders (keeps surrounding text)
        line = self.DOT_LEADER_RE.sub(' ', line)
        # Compress multiple spaces/tabs
        line = self.MULTIPLE_SPACES_RE.sub(' ', line)
        return line.strip()

    def clean_text(self, text: str) -> str:
        """Full document-level cleaning pipeline."""
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            if self.is_noise_line(line):
                continue
            cleaned_line = self.clean_line(line)
            if cleaned_line:
                cleaned.append(cleaned_line)
        return '\n'.join(cleaned)


# ---------------------------------------------------------------------------
# Regulation-Aware Chunker
# ---------------------------------------------------------------------------

class RegulationChunker:
    """
    Chunks Vietnamese administrative documents based on structural headings:
        • Chương  (Chapter)  — updates chapter context only
        • Mục     (Section)  — updates section context only
        • Điều    (Article)  — a new Điều triggers a new chunk
        • Khoản   (Clause)   — stays inside its parent Điều chunk

    Quality filters are applied before yielding chunks:
        • Minimum content length (avoids embedding header-only chunks)
        • Drop chunks flagged as low-information
    """

    CHUONG_RE = re.compile(
        r'^\s*Chương\s+([IVXLCDM]+|\d+)(?:[:\.\s]|$)',
        re.IGNORECASE
    )
    MUC_RE = re.compile(
        r'^\s*Mục\s+\d+(?:[:\.\s]|$)',
        re.IGNORECASE
    )
    DIEU_RE = re.compile(
        r'^\s*Điều\s+\d+(?:[:\.\s]|$)',
        re.IGNORECASE
    )
    PHU_LUC_RE = re.compile(
        r'^\s*Phụ\s+lục\s+([IVXLCDM]+|\d+)',
        re.IGNORECASE
    )
    BANG_RE = re.compile(
        r'Bảng\s+(\d+[\.\d]*)',
        re.IGNORECASE
    )

    def __init__(self, max_chunk_size: int = 2000, min_chunk_chars: int = 60):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_chars = min_chunk_chars
        self.cleaner = VietnameseRegulationCleaner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_document(self, raw_text: str, metadata: dict) -> list[dict]:
        """
        Main entry point. Accepts raw extracted text and base metadata dict
        (must contain at least 'filename'). Returns list of chunk dicts.
        """
        text = self.cleaner.clean_text(raw_text)
        lines = text.split('\n')

        chunks: list[dict] = []
        ctx = {
            "chapter":    "Phần mở đầu",
            "chapter_num": "",
            "section":    "",
            "article":    "",
            "article_num": "",
            "appendix":   "",
        }
        current_lines: list[str] = []

        def flush():
            content = '\n'.join(current_lines).strip()
            if self._is_quality_chunk(content):
                self._emit_chunks(content, dict(ctx), metadata, chunks)

        for line in lines:
            s = line.strip()
            if not s:
                continue

            # Matching headings regardless of leading spaces
            if self.PHU_LUC_RE.match(line):
                # Phụ lục (Appendix) → new chunk, reset article context
                flush()
                current_lines = [s]
                ctx["appendix"] = s
                ctx["article"] = ""
                ctx["article_num"] = ""
            elif self.CHUONG_RE.match(line):
                flush()
                current_lines = [s]
                ctx["chapter"] = s
                ctx["chapter_num"] = self._extract_number(s, r'Chương\s+([IVXLCDM]+|\d+)')
                ctx["section"] = ""
                ctx["article"] = ""
                ctx["article_num"] = ""
                ctx["appendix"] = ""
            elif self.MUC_RE.match(line):
                flush()
                current_lines = [s]
                ctx["section"] = s
            elif self.DIEU_RE.match(line):
                flush()
                current_lines = [s]
                ctx["article"] = s
                ctx["article_num"] = self._extract_number(s, r'Điều\s+(\d+)')
            else:
                current_lines.append(s)

        flush()

        # Post-process: merge header-only (tiny) chunks into the next chunk
        chunks = self._merge_short_chunks(chunks)
        return chunks

    def _merge_short_chunks(self, chunks: list[dict]) -> list[dict]:
        """
        Merges chunks that are too short (header-only stubs from TOC parsing)
        into the next chunk. The short chunk's content is prepended to the
        next chunk's content, and the merged chunk keeps the next chunk's metadata.
        """
        if not chunks:
            return chunks

        merged = []
        pending_content = ""

        for chunk in chunks:
            content = chunk["content"]

            if pending_content:
                # Prepend the short chunk's content to this chunk
                chunk["content"] = pending_content + "\n" + content
                pending_content = ""

            if len(chunk["content"]) < self.min_chunk_chars or len(chunk["content"].split()) < 5:
                # This chunk is too short — hold it for merging with next
                pending_content = chunk["content"]
            else:
                merged.append(chunk)

        # If the last chunk was short, append it to the previous chunk
        if pending_content and merged:
            merged[-1]["content"] += "\n" + pending_content
        elif pending_content:
            # Edge case: all chunks are short — keep the merged content as one
            merged.append({**chunks[-1], "content": pending_content})

        return merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_quality_chunk(self, content: str) -> bool:
        """Returns False for chunks that are too short or low-information."""
        if len(content) < self.min_chunk_chars:
            return False
        # Drop chunks that are almost entirely numeric (page/table artefacts)
        words = content.split()
        if len(words) < 3: # Relaxed from 5 to 3
            return False
        return True

    def _emit_chunks(self, content: str, ctx: dict, metadata: dict, out: list):
        """Adds one or more chunks to `out`, applying size-based splitting if needed."""
        filename = metadata.get("filename", "Unknown")

        def make_chunk(text: str, part: str = "1/1") -> dict:
            # Detect table labels inside chunk content
            table_match = self.BANG_RE.search(text)
            table_label = f"Bảng {table_match.group(1)}" if table_match else ""

            return {
                "id":          str(uuid.uuid4()),
                "document":    filename,
                "chapter":     ctx["chapter"],
                "chapter_num": ctx["chapter_num"],
                "section":     ctx["section"],
                "article":     ctx["article"],
                "article_num": ctx["article_num"],
                "appendix":    ctx.get("appendix", ""),
                "table_label": table_label,
                "part":        part,
                "content":     text.strip(),
                "citation":    self._build_citation(filename, ctx, table_label),
            }

        if len(content) <= self.max_chunk_size:
            out.append(make_chunk(content))
        else:
            sub_chunks = self._split_long_chunk(content)
            total = len(sub_chunks)
            for idx, sc in enumerate(sub_chunks):
                out.append(make_chunk(sc, part=f"{idx+1}/{total}"))

    def _split_long_chunk(self, text: str) -> list[str]:
        """
        Splits overlong chunks first at blank-line paragraph boundaries,
        then at sentence ends if still too long.
        """
        results = []
        current = ""

        for line in text.split('\n'):
            tentative = (current + '\n' + line).strip()
            if len(tentative) <= self.max_chunk_size:
                current = tentative
            else:
                if current:
                    results.append(current)
                # If single line is > max, split at sentence boundaries
                if len(line) > self.max_chunk_size:
                    for sentence in re.split(r'(?<=[.!?;])\s+', line):
                        if len(current) + len(sentence) <= self.max_chunk_size:
                            current = (current + ' ' + sentence).strip()
                        else:
                            if current:
                                results.append(current)
                            current = sentence
                else:
                    current = line

        if current.strip():
            results.append(current.strip())

        return results if results else [text]

    @staticmethod
    def _extract_number(text: str, pattern: str) -> str:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1) if m else ""

    @staticmethod
    def _build_citation(filename: str, ctx: dict, table_label: str = "") -> str:
        """Builds a human-readable Vietnamese citation string."""
        parts = [filename]
        if ctx.get("chapter"):
            parts.append(ctx["chapter"])
        if ctx.get("appendix"):
            parts.append(ctx["appendix"])
        if ctx.get("section"):
            parts.append(ctx["section"])
        if ctx.get("article"):
            parts.append(ctx["article"])
        if table_label:
            parts.append(table_label)
        return " > ".join(parts)
