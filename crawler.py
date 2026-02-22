#!/usr/bin/env python3
"""
Website Crawler Tool

Crawls websites and uses Claude AI to extract structured data from pages.
Results are saved as JSON or CSV.

Usage:
    python crawler.py <url> --data "<what to extract>" [options]

Examples:
    python crawler.py https://example.com --data "contact info: name, email, phone"
    python crawler.py https://shop.example.com --data "product name, price" --format csv --output products.csv
    python crawler.py https://example.com --data "addresses and place names" --max-pages 20 --depth 3
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(
        "Error: Required packages missing. Run:\n  pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

import anthropic


def fetch_page(url: str, timeout: int = 10) -> tuple[str | None, str]:
    """Fetch a webpage and return (html_content, final_url)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WebCrawler/1.0; +research)"}
    try:
        response = requests.get(
            url, headers=headers, timeout=timeout, allow_redirects=True
        )
        response.raise_for_status()
        return response.text, response.url
    except requests.RequestException as e:
        print(f"  Warning: Could not fetch {url}: {e}", file=sys.stderr)
        return None, url


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract all hyperlinks from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full_url = urljoin(base_url, href).split("#")[0]
        if full_url:
            links.add(full_url)
    return list(links)


def html_to_text(html: str) -> str:
    """Strip HTML tags and return clean readable text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


def extract_data_with_claude(
    client: anthropic.Anthropic,
    url: str,
    text: str,
    data_description: str,
    max_text_length: int = 8000,
) -> list[dict]:
    """Send page text to Claude and extract structured records as JSON."""
    if len(text) > max_text_length:
        text = text[:max_text_length] + "\n...[content truncated]"

    prompt = f"""Extract data from the webpage below.

URL: {url}
What to extract: {data_description}

Return ONLY a JSON array of objects — one object per data record found.
If no relevant data exists on the page, return an empty array: []
Do not include any explanation or markdown — just the raw JSON array.

Webpage content:
{text}"""

    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        result_text = next(
            (block.text for block in response.content if block.type == "text"),
            "[]",
        ).strip()

        # Isolate the JSON array in case Claude adds surrounding text
        start = result_text.find("[")
        end = result_text.rfind("]") + 1
        if start >= 0 and end > start:
            result_text = result_text[start:end]

        return json.loads(result_text)

    except (json.JSONDecodeError, anthropic.APIError) as e:
        print(f"  Warning: Data extraction failed for {url}: {e}", file=sys.stderr)
        return []


def crawl(
    seed_url: str,
    data_description: str,
    max_pages: int = 10,
    max_depth: int = 2,
    delay: float = 1.0,
    stay_on_domain: bool = True,
    url_pattern: str | None = None,
) -> list[dict]:
    """
    Crawl a website breadth-first and extract data from each page using Claude.

    Args:
        seed_url:         Starting URL.
        data_description: Natural-language description of what data to extract.
        max_pages:        Maximum pages to visit.
        max_depth:        Maximum link depth from seed URL.
        delay:            Seconds to wait between requests.
        stay_on_domain:   If True, ignore links outside the seed domain.
        url_pattern:      Optional regex — only crawl matching URLs.

    Returns:
        List of extracted data record dicts, each with a '_source_url' field.
    """
    client = anthropic.Anthropic()
    base_domain = urlparse(seed_url).netloc

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    all_results: list[dict] = []
    pages_crawled = 0

    print(f"Seed URL : {seed_url}")
    print(f"Extracting: {data_description}")
    print(f"Limits  : {max_pages} pages, depth {max_depth}")
    print("-" * 60)

    while queue and pages_crawled < max_pages:
        url, depth = queue.popleft()

        if url in visited:
            continue
        if stay_on_domain and urlparse(url).netloc != base_domain:
            continue
        if url_pattern and not re.search(url_pattern, url):
            continue

        visited.add(url)
        print(f"[{pages_crawled + 1}/{max_pages}] depth={depth}  {url}")

        html, final_url = fetch_page(url)
        if html is None:
            continue

        pages_crawled += 1
        text = html_to_text(html)

        print("  → Asking Claude to extract data...")
        records = extract_data_with_claude(client, url, text, data_description)

        if records:
            for record in records:
                record["_source_url"] = url
            all_results.extend(records)
            print(f"  ✓ {len(records)} record(s) found")
        else:
            print("  – No matching data on this page")

        if depth < max_depth:
            for link in extract_links(html, final_url):
                if link not in visited:
                    queue.append((link, depth + 1))

        if queue and pages_crawled < max_pages:
            time.sleep(delay)

    print("-" * 60)
    print(f"Done. Pages visited: {pages_crawled} | Total records: {len(all_results)}")
    return all_results


def save_results(results: list[dict], output_file: str, fmt: str = "json") -> None:
    """Write results to a JSON or CSV file."""
    if not results:
        print("No data extracted — nothing saved.")
        return

    if fmt == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    elif fmt == "csv":
        # Collect all field names in insertion order
        fieldnames: list[str] = []
        for record in results:
            for key in record:
                if key not in fieldnames:
                    fieldnames.append(key)
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)

    print(f"Results saved → {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl websites and extract structured data using Claude AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract contact info from a company site
  python crawler.py https://example.com --data "name, email, phone number"

  # Scrape product listings to a CSV file
  python crawler.py https://shop.example.com \\
      --data "product name, price, description" \\
      --format csv --output products.csv

  # Extract addresses for use with mapping.R
  python crawler.py https://example.com \\
      --data "business name and street address" \\
      --format csv --output addresses.csv --max-pages 30

  # Deep crawl with slow rate limiting
  python crawler.py https://example.com \\
      --data "article title and author" \\
      --max-pages 50 --depth 3 --delay 2
        """,
    )
    parser.add_argument("url", help="Seed URL to begin crawling")
    parser.add_argument(
        "--data",
        required=True,
        metavar="DESCRIPTION",
        help="What data to extract from each page (plain English)",
    )
    parser.add_argument(
        "--output",
        default="crawl_results.json",
        metavar="FILE",
        help="Output file path (default: crawl_results.json)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format: json or csv (default: json)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        metavar="N",
        help="Maximum pages to crawl (default: 10)",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=2,
        metavar="N",
        help="Maximum link depth from seed URL (default: 2)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Delay between requests in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--any-domain",
        action="store_true",
        help="Follow links to other domains (default: stay on seed domain)",
    )
    parser.add_argument(
        "--url-pattern",
        metavar="REGEX",
        help="Only crawl URLs matching this regex pattern",
    )

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY environment variable is not set.\n"
            "Export it with:  export ANTHROPIC_API_KEY=your_key_here",
            file=sys.stderr,
        )
        sys.exit(1)

    # Infer format from output filename if user didn't specify --format
    if args.output.endswith(".csv") and args.format == "json":
        args.format = "csv"

    results = crawl(
        seed_url=args.url,
        data_description=args.data,
        max_pages=args.max_pages,
        max_depth=args.depth,
        delay=args.delay,
        stay_on_domain=not args.any_domain,
        url_pattern=args.url_pattern,
    )

    save_results(results, args.output, args.format)

    if results:
        print("\nSample (first record):")
        print(json.dumps(results[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
