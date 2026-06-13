#!/usr/bin/env python3
"""
Web crawler for polgroup.ru using Playwright (headless Chrome).
Extracts: URL, title, meta description, content text.
Encoding: Windows-1251 (handled via page.content()).
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
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

BASE_URL = "https://polgroup.ru"
OUTPUT_DIR = Path("D:/Claude/Site") if sys.platform == "win32" else Path("./output")
DELAY = 1.5  # seconds between page loads
TIMEOUT = 20_000  # ms


def is_internal(url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(BASE_URL)
    skip_ext = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip",
                ".doc", ".docx", ".xls", ".xlsx", ".rar", ".mp4")
    if url.lower().endswith(skip_ext):
        return False
    if parsed.scheme in ("mailto", "tel", "javascript"):
        return False
    return parsed.netloc == "" or parsed.netloc == base.netloc


def collect_links(soup: BeautifulSoup, current_url: str) -> set[str]:
    links: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#"):
            continue
        full = urljoin(current_url, href).split("#")[0].rstrip("/")
        if is_internal(full) and full.startswith("http"):
            links.add(full)
    return links


def extract_data(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"}) or \
           soup.find("meta", attrs={"property": "og:description"})
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
    visited: set[str] = set()
    queue: list[str] = [BASE_URL]
    results: list[dict] = []

    print(f"Starting crawl : {BASE_URL}")
    print(f"Output dir     : {OUTPUT_DIR.resolve()}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            locale="ru-RU",
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
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

            data = extract_data(url, html)
            results.append(data)

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
