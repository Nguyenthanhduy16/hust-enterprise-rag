"""
Web Crawler for HUST Student Handbook (sv-ctt.hust.edu.vn)
==========================================================

This SPA (Vue.js) site requires a browser engine to render content.
We use Playwright (Chromium) to:
  1. Load the "Sổ tay sinh viên" list page
  2. Discover detail page URLs via <a href="#/so-tay-sv/{id}/{slug}">
  3. Navigate to each detail page and extract text + PDF links
  4. Download PDFs from ctt.hust.edu.vn (and skip SharePoint/GDrive links)
  5. Save text as .txt into data/raw/crawled_web/ for the ingest pipeline

Usage:
    python src/pipeline/web_crawler.py                  # crawl all items
    python src/pipeline/web_crawler.py --items 1 3 8    # crawl items #1, #3 and #8 only
    python src/pipeline/web_crawler.py --pdfs-only      # only download PDFs, skip text
    python src/pipeline/web_crawler.py --visible        # show browser window for debugging

After crawling, run:
    python src/pipeline/ingest.py        # chunk text + PDFs
    python src/pipeline/embed_and_store.py  # embed into ChromaDB
"""

import re
import os
import sys
import json
import time
import argparse
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin, unquote, urlparse, quote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
CRAWLED_DIR = RAW_DIR / "crawled_web"       # text extracted from web pages
PDF_DIR = RAW_DIR                            # PDFs go alongside existing PDFs
LOG_DIR = PROJECT_ROOT / "data" / "crawl_logs"

BASE_URL = "https://sv-ctt.hust.edu.vn"
HANDBOOK_URL = f"{BASE_URL}/#/so-tay-sv"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "crawl.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Make a string safe for use as a filename."""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len]
    return name


def download_pdf(url: str, dest_dir: Path) -> Path | None:
    """Download a PDF file via HTTP. Returns the saved path or None."""
    try:
        parsed = urlparse(url)
        filename = unquote(parsed.path.split('/')[-1])
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        filename = sanitize_filename(filename)

        dest_path = dest_dir / filename
        if dest_path.exists():
            log.info(f"    [SKIP] Already downloaded: {filename}")
            return dest_path

        log.info(f"    [DOWNLOAD] {filename}")
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = dest_path.stat().st_size / 1024
        log.info(f"    [OK] Saved: {filename} ({size_kb:.0f} KB)")
        return dest_path

    except Exception as e:
        log.warning(f"    [FAIL] Could not download {url}: {e}")
        return None


def _table_to_markdown(table_tag) -> str:
    """Convert an HTML <table> into a Markdown table string."""
    rows = table_tag.find_all('tr')
    if not rows:
        return ""

    md_rows = []
    for row in rows:
        cells = row.find_all(['th', 'td'])
        # Get text from each cell, collapsing whitespace
        cell_texts = []
        for cell in cells:
            # Preserve links inside cells
            text_parts = []
            for child in cell.children:
                if hasattr(child, 'name') and child.name == 'a' and child.get('href'):
                    link_text = child.get_text(strip=True)
                    href = child['href'].strip()
                    if href and not href.startswith('#') and not href.startswith('javascript'):
                        text_parts.append(f"{link_text} ({href})" if link_text else href)
                    else:
                        text_parts.append(link_text)
                else:
                    t = child.get_text(strip=True) if hasattr(child, 'get_text') else str(child).strip()
                    if t:
                        text_parts.append(t)
            cell_text = ' '.join(text_parts).strip()
            # Replace pipes and newlines that would break MD table
            cell_text = cell_text.replace('|', '/').replace('\n', ' ')
            cell_texts.append(cell_text)

        if any(cell_texts):  # skip empty rows
            md_rows.append('| ' + ' | '.join(cell_texts) + ' |')

    if not md_rows:
        return ""

    # Insert header separator after first row
    num_cols = max(row.count('|') - 1 for row in md_rows) if md_rows else 0
    if num_cols <= 0:
        num_cols = len(md_rows[0].split('|')) - 2
    separator = '| ' + ' | '.join(['---'] * max(num_cols, 1)) + ' |'

    result = [md_rows[0], separator] + md_rows[1:]
    return '\n'.join(result)


def _element_to_text(element) -> str:
    """Convert a single HTML element to RAG-friendly text, preserving links."""
    parts = []
    for child in element.children:
        if hasattr(child, 'name'):
            if child.name == 'a' and child.get('href'):
                link_text = child.get_text(strip=True)
                href = child['href'].strip()
                # Skip anchor-only or javascript links
                if href and not href.startswith('#/') == False and not href.startswith('javascript'):
                    if link_text and href.startswith('http'):
                        parts.append(f"{link_text} ({href})")
                    elif href.startswith('http'):
                        parts.append(href)
                    else:
                        parts.append(link_text or href)
                else:
                    parts.append(link_text)
            elif child.name == 'br':
                parts.append('\n')
            elif child.name == 'strong' or child.name == 'b':
                t = child.get_text(strip=True)
                if t:
                    parts.append(f"**{t}**")
            else:
                t = child.get_text(strip=True)
                if t:
                    parts.append(t)
        else:
            t = str(child).strip()
            if t:
                parts.append(t)
    return ' '.join(parts).strip()


def extract_structured_text(html: str, title: str = "") -> str:
    """
    Convert HTML to RAG-optimized structured text.

    - Tables → Markdown tables (preserving row/column relationships)
    - Links  → inline text (URL) format
    - Headings → Markdown ## headings
    - Lists → bullet points with -
    - Paragraphs → clean text blocks
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove noisy elements
    for selector in ["nav", "footer", ".el-menu", ".sidebar",
                      "script", "style", ".el-menu-item", ".btn-login"]:
        for tag in soup.select(selector):
            tag.decompose()

    lines = []

    # Prepend document title
    if title:
        lines.append(f"# {title}")
        lines.append("")

    # Find the content container
    container = soup.select_one(".tip-detail, .el-main, .main-container")
    if not container:
        container = soup

    # Walk through top-level children of the container in document order
    for element in container.descendants:
        # Only process direct element nodes, skip NavigableString
        if not hasattr(element, 'name') or element.name is None:
            continue

        # Skip elements that are children of elements we already processed
        # (e.g., <td> inside <table> — table is handled as a whole)
        if element.find_parent('table'):
            continue
        if element.find_parent('li'):
            continue

        tag = element.name

        if tag == 'table':
            md_table = _table_to_markdown(element)
            if md_table:
                lines.append("")
                lines.append(md_table)
                lines.append("")

        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            level = int(tag[1])
            heading_text = element.get_text(strip=True)
            if heading_text:
                lines.append("")
                lines.append(f"{'#' * level} {heading_text}")
                lines.append("")

        elif tag == 'li':
            text = _element_to_text(element)
            if text:
                lines.append(f"- {text}")

        elif tag == 'p':
            text = _element_to_text(element)
            if text:
                lines.append(text)
                lines.append("")

        elif tag == 'blockquote':
            text = element.get_text(strip=True)
            if text:
                lines.append(f"> {text}")
                lines.append("")

    # Clean up: remove excessive blank lines
    result = '\n'.join(lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()



def find_pdf_links(soup: BeautifulSoup) -> list[dict]:
    """Extract all PDF download links from parsed HTML."""
    links = []
    seen = set()

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        if not href:
            continue

        # Resolve relative URLs
        full_url = urljoin(BASE_URL + "/", href)

        # Only consider direct PDF links from ctt.hust.edu.vn
        is_direct_pdf = (
            '.pdf' in href.lower() and
            ('ctt.hust.edu.vn' in full_url or 'sv-ctt.hust.edu.vn' in full_url)
        )

        if is_direct_pdf and full_url not in seen:
            seen.add(full_url)
            link_text = a_tag.get_text(strip=True) or "Unknown"
            links.append({"url": full_url, "text": link_text})

    return links


# ---------------------------------------------------------------------------
# Main Crawler
# ---------------------------------------------------------------------------

class HUSTHandbookCrawler:
    """
    Crawls the HUST Student Handbook SPA using Playwright.

    Strategy:
      Phase 1 — Load list page, extract all <a href="#/so-tay-sv/{id}/{slug}"> links
      Phase 2 — Navigate to each detail URL, extract text + PDF links
      Phase 3 — Download discovered PDFs
    """

    def __init__(self, headless: bool = True, timeout: int = 15000):
        self.headless = headless
        self.timeout = timeout
        self.crawl_report = {
            "items_found": 0,
            "items_crawled": 0,
            "text_files_saved": 0,
            "pdfs_downloaded": 0,
            "pdf_failed": 0,
            "errors": [],
        }

    def run(self, target_items: list[int] | None = None, pdfs_only: bool = False):
        """Main entry point."""
        CRAWLED_DIR.mkdir(parents=True, exist_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)

        log.info("=" * 60)
        log.info("HUST Student Handbook Crawler")
        log.info(f"Target URL : {HANDBOOK_URL}")
        log.info(f"Text output: {CRAWLED_DIR}")
        log.info(f"PDF output : {PDF_DIR}")
        if target_items:
            log.info(f"Items filter: {target_items}")
        log.info("=" * 60)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
            )
            page = context.new_page()

            try:
                # Phase 1: Discover all detail page URLs
                detail_pages = self._discover_items(page)
                self.crawl_report["items_found"] = len(detail_pages)

                # Phase 2 & 3: Visit each page, extract content and download PDFs
                for idx, item in enumerate(detail_pages):
                    item_num = idx + 1
                    if target_items and item_num not in target_items:
                        continue

                    log.info(f"\n{'─' * 55}")
                    log.info(f"[{item_num}/{len(detail_pages)}] {item['title']}")

                    try:
                        self._process_item(page, item, item_num, pdfs_only)
                        self.crawl_report["items_crawled"] += 1
                    except Exception as e:
                        log.error(f"  Error processing item {item_num}: {e}")
                        self.crawl_report["errors"].append(f"Item {item_num}: {e}")

            except Exception as e:
                log.error(f"Critical error: {e}", exc_info=True)
                self.crawl_report["errors"].append(str(e))
            finally:
                browser.close()

        self._print_report()
        self._save_report()

    def _discover_items(self, page) -> list[dict]:
        """
        Phase 1: Load the handbook list page and extract all item links.
        Returns list of dicts with 'url', 'title', 'href'.
        """
        log.info("Phase 1: Discovering handbook items...")
        page.goto(HANDBOOK_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # The SPA uses <a href="#/so-tay-sv/{id}/{slug}"> for each item
        link_elements = page.query_selector_all("a[href*='/so-tay-sv/']")

        items = []
        seen_hrefs = set()

        for el in link_elements:
            href = el.get_attribute("href") or ""
            # Filter: only detail page links (has an ID segment after /so-tay-sv/)
            if re.match(r'#/so-tay-sv/\d+', href) and href not in seen_hrefs:
                seen_hrefs.add(href)
                title = el.inner_text().strip().split('\n')[0]
                full_url = f"{BASE_URL}/{href}"
                items.append({
                    "href": href,
                    "url": full_url,
                    "title": title,
                })

        log.info(f"Found {len(items)} handbook items:")
        for i, item in enumerate(items):
            log.info(f"  {i+1}. {item['title'][:70]}")

        return items

    def _process_item(self, page, item: dict, item_num: int, pdfs_only: bool):
        """Phase 2 & 3: Navigate to detail page, extract text and PDFs."""
        # Navigate to the detail page
        page.goto(item["url"], wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # Get page content
        html = page.content()
        soup = BeautifulSoup(html, "lxml")

        # --- Extract & download PDFs ---
        pdf_links = find_pdf_links(soup)
        if pdf_links:
            log.info(f"  📄 Found {len(pdf_links)} PDF(s):")
            for pinfo in pdf_links:
                log.info(f"    • {pinfo['text'][:80]}")
                result = download_pdf(pinfo['url'], PDF_DIR)
                if result:
                    self.crawl_report["pdfs_downloaded"] += 1
                else:
                    self.crawl_report["pdf_failed"] += 1
        else:
            log.info("  📄 No direct PDF links found on this page.")

        # --- Extract text content ---
        if not pdfs_only:
            # The SPA renders content into a div.tip-detail container.
            # We get its innerHTML and convert to structured text (tables, links, headings).
            max_retries = 4
            text = ""
            for attempt in range(max_retries):
                try:
                    # .tip-detail is the actual content container in the HUST SPA
                    page.wait_for_selector(".tip-detail", state="visible", timeout=5000)
                    page.wait_for_timeout(1000)  # small buffer for text population

                    # Get innerHTML to preserve table/link structure
                    detail_html = page.evaluate("""() => {
                        const detail = document.querySelector('.tip-detail');
                        if (detail) return detail.innerHTML;
                        const main = document.querySelector('.main-container')
                                  || document.querySelector('#app');
                        return main ? main.innerHTML : document.body.innerHTML;
                    }""")

                    if detail_html and len(detail_html.strip()) > 100:
                        text = extract_structured_text(detail_html, title=item['title'])
                        if len(text) > len(item['title']) + 50:
                            break

                    log.info(f"    [Retry {attempt+1}/{max_retries}] Content too short, waiting...")
                    page.wait_for_timeout(2000)

                except PlaywrightTimeout:
                    log.info(f"    [Retry {attempt+1}/{max_retries}] Timeout waiting for .tip-detail...")
                    # Fallback: get full page HTML
                    try:
                        full_html = page.content()
                        text = extract_structured_text(full_html, title=item['title'])
                        if len(text) > len(item['title']) + 100:
                            break
                    except:
                        pass
                    page.wait_for_timeout(2000)

            if text and len(text) > len(item['title']) + 50:
                safe_title = sanitize_filename(item['title'])
                filename = f"{item_num:02d}_{safe_title}.txt"
                out_path = CRAWLED_DIR / filename

                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)

                log.info(f"  📝 Text saved: {filename} ({len(text)} chars)")
                self.crawl_report["text_files_saved"] += 1
            else:
                log.info("  📝 Text content too short or empty, skipped.")

    def _print_report(self):
        """Print a summary report."""
        r = self.crawl_report
        log.info("\n" + "=" * 60)
        log.info("CRAWL REPORT")
        log.info("=" * 60)
        log.info(f"  Items found:        {r['items_found']}")
        log.info(f"  Items crawled:      {r['items_crawled']}")
        log.info(f"  Text files saved:   {r['text_files_saved']}")
        log.info(f"  PDFs downloaded:    {r['pdfs_downloaded']}")
        log.info(f"  PDF failures:       {r['pdf_failed']}")
        log.info(f"  Errors:             {len(r['errors'])}")
        if r['errors']:
            for err in r['errors']:
                log.warning(f"    ✗ {err}")
        log.info("=" * 60)

    def _save_report(self):
        """Save the crawl report as JSON."""
        report_path = LOG_DIR / "crawl_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.crawl_report, f, ensure_ascii=False, indent=2)
        log.info(f"Report saved: {report_path}")


# ---------------------------------------------------------------------------
# Also crawl "QUY ĐỊNH" (Regulations) tab
# ---------------------------------------------------------------------------

class HUSTRegulationsCrawler(HUSTHandbookCrawler):
    """
    Extends the handbook crawler to also crawl the "QUY ĐỊNH" section.
    URL pattern: https://sv-ctt.hust.edu.vn/#/quy-dinh
    """

    REGULATIONS_URL = f"{BASE_URL}/#/quy-dinh"

    def run_regulations(self, pdfs_only: bool = False):
        """Crawl the Quy Định (Regulations) section."""
        CRAWLED_DIR.mkdir(parents=True, exist_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)

        log.info("=" * 60)
        log.info("HUST Regulations Crawler (Quy Định)")
        log.info(f"Target URL : {self.REGULATIONS_URL}")
        log.info("=" * 60)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
            )
            page = context.new_page()

            try:
                page.goto(self.REGULATIONS_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                # Find all regulation detail links
                link_elements = page.query_selector_all("a[href*='/quy-dinh/']")

                items = []
                seen = set()
                for el in link_elements:
                    href = el.get_attribute("href") or ""
                    if re.match(r'#/quy-dinh/\d+', href) and href not in seen:
                        seen.add(href)
                        title = el.inner_text().strip().split('\n')[0]
                        items.append({
                            "href": href,
                            "url": f"{BASE_URL}/{href}",
                            "title": title,
                        })

                log.info(f"Found {len(items)} regulation items.")

                for idx, item in enumerate(items):
                    item_num = idx + 1
                    log.info(f"\n[{item_num}/{len(items)}] {item['title'][:70]}")
                    try:
                        self._process_item(page, item, item_num + 100, pdfs_only)  # offset numbering
                    except Exception as e:
                        log.error(f"  Error: {e}")

            except Exception as e:
                log.error(f"Critical error: {e}", exc_info=True)
            finally:
                browser.close()

        self._print_report()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Crawl HUST Student Handbook & Regulations (sv-ctt.hust.edu.vn)"
    )
    parser.add_argument(
        "--items", nargs="*", type=int, default=None,
        help="Item numbers to crawl (1-indexed). If not set, crawl all."
    )
    parser.add_argument(
        "--pdfs-only", action="store_true",
        help="Only download PDFs, skip text extraction."
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Run browser in visible mode (not headless) for debugging."
    )
    parser.add_argument(
        "--timeout", type=int, default=15000,
        help="Timeout in ms for page loads (default: 15000)."
    )
    parser.add_argument(
        "--include-regulations", action="store_true",
        help="Also crawl the QUY ĐỊNH (Regulations) section."
    )

    args = parser.parse_args()

    crawler = HUSTRegulationsCrawler(
        headless=not args.visible,
        timeout=args.timeout,
    )

    # Crawl handbook
    crawler.run(
        target_items=args.items,
        pdfs_only=args.pdfs_only,
    )

    # Optionally crawl regulations too
    if args.include_regulations:
        crawler.run_regulations(pdfs_only=args.pdfs_only)


if __name__ == "__main__":
    main()
