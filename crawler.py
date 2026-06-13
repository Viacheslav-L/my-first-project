#!/usr/bin/env python3
"""
Web crawler for polgroup.ru
Extracts: URL, title, meta description, content text
Encoding: Windows-1251
Output: CSV + JSON
"""

import csv
import json
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://polgroup.ru"
OUTPUT_DIR = Path("D:/Claude/Site") if __import__("sys").platform == "win32" else Path("./output")
DELAY = 1.0  # seconds between requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "windows-1251"
        if resp.status_code != 200:
            print(f"  [SKIP] {url} → HTTP {resp.status_code}")
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [ERROR] {url} → {e}")
        return None


def extract_data(url: str, soup: BeautifulSoup) -> dict:
    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if not meta_tag:
        meta_tag = soup.find("meta", attrs={"property": "og:description"})
    if meta_tag:
        meta_desc = meta_tag.get("content", "").strip()

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    body = soup.find("body")
    content = " ".join(body.get_text(separator=" ").split()) if body else ""

    return {
        "url": url,
        "title": title,
        "meta_description": meta_desc,
        "content": content,
    }


def is_internal(url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(BASE_URL)
    return (parsed.netloc == "" or parsed.netloc == base.netloc) and \
           not parsed.scheme.startswith("mailto") and \
           not parsed.scheme.startswith("tel") and \
           not url.endswith((".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx"))


def collect_links(soup: BeautifulSoup, current_url: str) -> set:
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#"):
            continue
        full = urljoin(current_url, href).split("#")[0].rstrip("/")
        if is_internal(full):
            links.add(full)
    return links


def crawl() -> list[dict]:
    visited: set[str] = set()
    queue: list[str] = [BASE_URL]
    results: list[dict] = []

    print(f"Starting crawl: {BASE_URL}")
    print(f"Output dir   : {OUTPUT_DIR.resolve()}\n")

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        print(f"[{len(visited)}] {url}")
        soup = fetch_page(url)
        if soup is None:
            continue

        data = extract_data(url, soup)
        results.append(data)

        new_links = collect_links(soup, url) - visited
        queue.extend(new_links)

        time.sleep(DELAY)

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
    pages = crawl()
    save_results(pages)
