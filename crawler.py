#!/usr/bin/env python3
"""
Web crawler for polgroup.ru using Playwright (headless Chrome).
- Crawls structural HTML pages → extracts URL, title, meta, content text
- Downloads PDF, RAR, MP4 files found on any page
- Output: CSV + JSON (pages) + downloaded files in subfolders

Install:
    pip install playwright beautifulsoup4 requests
    playwright install chromium
Run:
    python crawler.py
"""

import asyncio
import csv
import json
import sys
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

BASE_URL = "https://polgroup.ru"
OUTPUT_DIR = Path("D:/Documents/Сайт/ГРУПП") if sys.platform == "win32" else Path("./output")
DELAY = 1.0
TIMEOUT = 20_000

SKIP_IMG_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
                       ".doc", ".docx", ".xls", ".xlsx", ".zip")

# These we DOWNLOAD, not skip
DOWNLOAD_EXTENSIONS = (".pdf", ".rar", ".mp4")

# Structural pages only (no individual product .html cards)
SKIP_MODULES = {"sitemap", "news", "articles"}
SKIP_PATH_PREFIXES = ("/Сайт/", "/catalog/", "/product/", "/tovar/")

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def normalize_url(url: str) -> str:
    p = urlparse(url)
    normalized = p._replace(scheme="https", fragment="", netloc=p.netloc.lower())
    path = normalized.path.rstrip("/") or "/"
    return urlunparse(normalized._replace(path=path))


def is_downloadable(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOWNLOAD_EXTENSIONS)


def is_crawlable(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc or p.netloc.replace("www.", "") != "polgroup.ru":
        return False
    if any(urlparse(url).path.lower().endswith(ext) for ext in SKIP_IMG_EXTENSIONS + DOWNLOAD_EXTENSIONS):
        return False
    if p.path.lower().endswith(".html"):
        return False
    if any(p.path.startswith(pfx) for pfx in SKIP_PATH_PREFIXES):
        return False
    qs = parse_qs(p.query)
    if qs.get("module", [""])[0] in SKIP_MODULES:
        return False
    return True


def collect_links(soup: BeautifulSoup, current_url: str) -> tuple[set[str], set[str]]:
    """Returns (crawlable_pages, downloadable_files)."""
    pages: set[str] = set()
    files: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = normalize_url(urljoin(current_url, href))
        if is_downloadable(full):
            files.add(full)
        elif is_crawlable(full):
            pages.add(full)
    return pages, files


def extract_data(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    meta = (soup.find("meta", attrs={"name": "description"}) or
            soup.find("meta", attrs={"property": "og:description"}))
    if meta:
        meta_desc = meta.get("content", "").strip()
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    body = soup.find("body")
    content = " ".join(body.get_text(separator=" ").split()) if body else ""
    return {"url": url, "title": title, "meta_description": meta_desc, "content": content}


def download_file(url: str, base_dir: Path) -> str:
    """Download file, save to subfolder by type. Returns local path or error."""
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        folder = base_dir / "PDF"
    elif path.endswith(".rar"):
        folder = base_dir / "RAR"
    elif path.endswith(".mp4"):
        folder = base_dir / "VIDEO"
    else:
        folder = base_dir / "FILES"
    folder.mkdir(parents=True, exist_ok=True)

    filename = Path(urlparse(url).path).name or "file"
    # sanitize filename
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    dest = folder / filename

    if dest.exists():
        return f"EXISTS {dest}"
    try:
        r = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        size_kb = dest.stat().st_size // 1024
        return f"OK {dest} ({size_kb} KB)"
    except Exception as e:
        return f"ERROR {e}"


async def fetch_html(page: Page, url: str) -> str | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(DELAY)
        return await page.content()
    except Exception as e:
        print(f"  [ERROR] {url} → {e}")
        return None


async def crawl() -> list[dict]:
    start = normalize_url(BASE_URL)
    visited_pages: set[str] = set()
    visited_files: set[str] = set()
    queue: list[str] = [start]
    results: list[dict] = []

    print(f"Starting crawl : {BASE_URL}")
    print(f"Output dir     : {OUTPUT_DIR.resolve()}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ru-RU",
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = await context.new_page()

        while queue:
            url = queue.pop(0)
            if url in visited_pages:
                continue
            visited_pages.add(url)
            print(f"[page {len(visited_pages)}] {url}")

            html = await fetch_html(page, url)
            if html is None:
                continue

            results.append(extract_data(url, html))

            soup = BeautifulSoup(html, "html.parser")
            new_pages, new_files = collect_links(soup, url)

            queue.extend(new_pages - visited_pages)

            # Download new files immediately
            for file_url in new_files - visited_files:
                visited_files.add(file_url)
                print(f"  [download] {file_url}")
                status = download_file(file_url, OUTPUT_DIR)
                print(f"    → {status}")

        await browser.close()

    print(f"\nPages crawled : {len(results)}")
    print(f"Files found   : {len(visited_files)}")
    return results


def save_results(results: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "polgroup_pages.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"JSON saved → {json_path}")

    csv_path = OUTPUT_DIR / "polgroup_pages.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "meta_description", "content"])
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV  saved → {csv_path}")


if __name__ == "__main__":
    pages = asyncio.run(crawl())
    save_results(pages)
