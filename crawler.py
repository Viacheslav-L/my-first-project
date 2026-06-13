#!/usr/bin/env python3
"""
Web crawler for polgroup.ru using Playwright (headless Chrome).
Extracts: URL, title, meta description, content text.
Output: CSV + JSON to OUTPUT_DIR.

Install:
    pip install playwright beautifulsoup4
    playwright install chromium
Run:
    python crawler.py
"""

import asyncio
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

BASE_URL = "https://polgroup.ru"
OUTPUT_DIR = Path("D:/Documents/Сайт/ГРУПП") if sys.platform == "win32" else Path("./output")
DELAY = 1.0
TIMEOUT = 20_000

SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip",
                   ".doc", ".docx", ".xls", ".xlsx", ".rar", ".mp4", ".svg", ".ico")

# Query params that generate duplicate/useless pages
SKIP_MODULES = {"sitemap", "news", "articles"}

# Path prefixes that lead to product catalog pages (thousands of items)
SKIP_PATH_PREFIXES = ("/Сайт/", "/catalog/", "/product/", "/tovar/")


def normalize_url(url: str) -> str:
    """Force https, strip trailing slash, remove fragment."""
    p = urlparse(url)
    normalized = p._replace(scheme="https", fragment="", netloc=p.netloc.lower())
    path = normalized.path.rstrip("/") or "/"
    return urlunparse(normalized._replace(path=path))


def is_crawlable(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc or p.netloc.replace("www.", "") != "polgroup.ru":
        return False
    if any(url.lower().endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    # Skip individual .html product pages (e.g. /mtg63.html, /galoshi.html)
    if p.path.lower().endswith(".html"):
        return False
    # Skip known catalog path prefixes
    if any(p.path.startswith(pfx) for pfx in SKIP_PATH_PREFIXES):
        return False
    # Skip pagination and module pages like ?module=news&page=2
    qs = parse_qs(p.query)
    module = qs.get("module", [""])[0]
    if module in SKIP_MODULES:
        return False
    return True


def collect_links(soup: BeautifulSoup, current_url: str) -> set[str]:
    links: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = normalize_url(urljoin(current_url, href))
        if is_crawlable(full):
            links.add(full)
    return links


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


async def fetch(page: Page, url: str) -> str | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        await asyncio.sleep(DELAY)
        return await page.content()
    except Exception as e:
        print(f"  [ERROR] {url} → {e}")
        return None


async def crawl() -> list[dict]:
    start = normalize_url(BASE_URL)
    visited: set[str] = set()
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
            if url in visited:
                continue
            visited.add(url)
            print(f"[{len(visited)}] {url}")

            html = await fetch(page, url)
            if html is None:
                continue

            results.append(extract_data(url, html))

            soup = BeautifulSoup(html, "html.parser")
            new_links = collect_links(soup, url) - visited
            queue.extend(new_links)

        await browser.close()

    return results


def save_results(results: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "polgroup_pages.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nJSON saved → {json_path}")

    csv_path = OUTPUT_DIR / "polgroup_pages.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "meta_description", "content"])
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV  saved → {csv_path}")
    print(f"\nTotal pages crawled: {len(results)}")


if __name__ == "__main__":
    pages = asyncio.run(crawl())
    save_results(pages)
