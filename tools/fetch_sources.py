"""Fetch raw content from all verified rifle-competition sources (Phase 3: Fetch).

Deterministic fetch only — no LLM extraction here. Each run writes raw
markdown/JSON into .tmp/raw/ plus a manifest at .tmp/fetch_manifest.json.
The extraction step (raw text -> structured records matching the Phase 2
schema in workflows/scan_rifle_competitions.md) is done by the agent reading
that manifest, per the WAT split between deterministic tools and agent
judgment.

Usage:
    python tools/fetch_sources.py                  # fetch all daily sources
    python tools/fetch_sources.py --source nrai     # fetch one source
    python tools/fetch_sources.py --list            # list available sources
    python tools/fetch_sources.py --yearly-sweep    # also run the weekly
                                                     # next-year-calendar sweep
                                                     # (costs extra SerpAPI
                                                     # calls — only run this
                                                     # on the weekly schedule,
                                                     # not the daily one)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, ".tmp", "raw")
MANIFEST_PATH = os.path.join(PROJECT_ROOT, ".tmp", "fetch_manifest.json")

FIRECRAWL_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY", "")

MAX_FOLLOWED_LINKS_PER_SOURCE = 15  # cost control on Firecrawl calls


def slugify(text: str) -> str:
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:80]


FIRECRAWL_PACING_SECONDS = 6.5  # learned 2026-08-31: Firecrawl returned 429s when
# hit back-to-back with no delay; this project's plan tier allows roughly one
# request per ~6-7s sustained. Retry-with-backoff below handles the rest.
_last_firecrawl_call = [0.0]


def firecrawl_scrape(url: str, formats=("markdown",), max_retries: int = 5) -> dict:
    # Pace calls so we don't even trigger the rate limit in the common case.
    elapsed = time.monotonic() - _last_firecrawl_call[0]
    if elapsed < FIRECRAWL_PACING_SECONDS:
        time.sleep(FIRECRAWL_PACING_SECONDS - elapsed)

    for attempt in range(max_retries + 1):
        _last_firecrawl_call[0] = time.monotonic()
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}"},
            json={"url": url, "formats": list(formats)},
            timeout=60,
        )
        if resp.status_code == 429 and attempt < max_retries:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else (2 ** attempt) * 3
            print(f"  [rate limited] {url} -> waiting {wait:.0f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success", True) and "data" not in body:
            raise RuntimeError(f"Firecrawl error for {url}: {body}")
        return body.get("data", {})
    raise RuntimeError(f"Firecrawl rate limit persisted after {max_retries} retries for {url}")


def serpapi_search(query: str, num: int = 10) -> list:
    resp = requests.get(
        "https://serpapi.com/search.json",
        params={"q": query, "api_key": SERPAPI_KEY, "engine": "google", "num": num},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"SerpAPI error for '{query}': {data['error']}")
    return data.get("organic_results", [])


def write_raw(name: str, content: str, ext: str = "md") -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    filename = f"{slugify(name)}.{ext}"
    path = os.path.join(RAW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return os.path.relpath(path, PROJECT_ROOT)


# Matches [text](url) and [text](url "optional title") — markdown link
# titles (common on MRA's circular links) broke a stricter version of this.
MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')


def find_pdf_links(links: list, markdown: str = "", must_contain: str = None, must_not_contain=None) -> list:
    """Find candidate PDF/circular links. `must_contain` (e.g. a year) is
    matched against the markdown LINK TEXT, not the URL — on sites like NRAI
    the URLs are opaque GUIDs and the year only appears in the visible title
    (e.g. "[CALENDAR 2026- RIFLE/PISTOL EVENTS](...guid...pdf)").
    `must_not_contain` (string or list of strings) excludes irrelevant items
    (e.g. Shotgun-only calendars, or "relay"/squad-list PDFs that are
    logistics documents rather than the actual eligibility/deadline circular)
    to avoid wasting Firecrawl calls on low-value PDFs — checked against both
    the link text and the URL, since some circulars only reveal their nature
    in the filename (e.g. "MAFC.Shotgun.2026.1...pdf") while the visible text
    is just the generic word "Circular"."""
    exclude_terms = []
    if must_not_contain:
        exclude_terms = [must_not_contain] if isinstance(must_not_contain, str) else list(must_not_contain)
    exclude_terms = [t.lower() for t in exclude_terms]

    candidates = []
    # Prefer markdown [text](url) pairs so we can filter on visible text.
    for text, url in MD_LINK_RE.findall(markdown or ""):
        if not url.startswith("http"):
            continue
        lower_url = url.lower()
        lower_text = text.lower()
        combined = f"{lower_text} {lower_url}"
        if ".pdf" in lower_url or "/pdf/" in lower_url or "/file/" in lower_url:
            if any(term in combined for term in exclude_terms):
                continue
            if must_contain is None or must_contain.lower() in combined:
                candidates.append(url)

    # Fall back to the plain links list (no text to filter on) if markdown
    # parsing found nothing — better to over-fetch than silently skip a source.
    if not candidates:
        for link in links or []:
            lower = link.lower()
            if ".pdf" in lower or "/pdf/" in lower or "/file/" in lower:
                if must_contain is None:
                    candidates.append(link)

    # de-dupe, preserve order
    seen = set()
    result = []
    for link in candidates:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


def fetch_page_and_linked_pdfs(manifest: list, source_name: str, url: str, pdf_filter: str = None, pdf_exclude: str = None):
    """Fetch a listing page (markdown + links), then follow any PDF/circular
    links found on it, up to MAX_FOLLOWED_LINKS_PER_SOURCE."""
    try:
        data = firecrawl_scrape(url, formats=["markdown", "links"])
        markdown = data.get("markdown", "")
        path = write_raw(source_name, markdown, "md")
        manifest.append({
            "source": source_name, "url": url, "file": path,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "ok",
        })
    except Exception as e:
        manifest.append({
            "source": source_name, "url": url, "file": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": f"error: {e}",
        })
        return

    pdf_links = find_pdf_links(data.get("links", []), markdown=markdown, must_contain=pdf_filter, must_not_contain=pdf_exclude)
    if len(pdf_links) > MAX_FOLLOWED_LINKS_PER_SOURCE:
        print(f"  [{source_name}] found {len(pdf_links)} PDF links, following first {MAX_FOLLOWED_LINKS_PER_SOURCE}")
        pdf_links = pdf_links[:MAX_FOLLOWED_LINKS_PER_SOURCE]

    for link in pdf_links:
        child_name = f"{source_name}__{slugify(link)}"
        try:
            pdf_data = firecrawl_scrape(link, formats=["markdown"])
            path = write_raw(child_name, pdf_data.get("markdown", ""), "md")
            manifest.append({
                "source": f"{source_name} (linked circular)", "url": link, "file": path,
                "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "ok",
            })
        except Exception as e:
            manifest.append({
                "source": f"{source_name} (linked circular)", "url": link, "file": None,
                "fetched_at": datetime.now(timezone.utc).isoformat(), "status": f"error: {e}",
            })


def fetch_simple_page(manifest: list, source_name: str, url: str):
    try:
        data = firecrawl_scrape(url, formats=["markdown"])
        path = write_raw(source_name, data.get("markdown", ""), "md")
        manifest.append({
            "source": source_name, "url": url, "file": path,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "ok",
        })
    except Exception as e:
        manifest.append({
            "source": source_name, "url": url, "file": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": f"error: {e}",
        })


def fetch_serpapi_source(manifest: list, source_name: str, query: str):
    try:
        results = serpapi_search(query)
        path = write_raw(source_name, json.dumps(results, indent=2), "json")
        manifest.append({
            "source": source_name, "url": f"serpapi:{query}", "file": path,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "ok",
        })
    except Exception as e:
        manifest.append({
            "source": source_name, "url": f"serpapi:{query}", "file": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": f"error: {e}",
        })


# Source registry — matches workflows/scan_rifle_competitions.md "Verified sources"
DAILY_SOURCES = {
    "nrai": lambda m: fetch_page_and_linked_pdfs(
        m, "nrai_calendar_page", "https://www.thenrai.in/shooting_calander.aspx",
        pdf_filter="2026", pdf_exclude="shotgun"
    ),
    "nrai_news": lambda m: fetch_simple_page(
        m, "nrai_news_events", "https://www.thenrai.in/news_events_details.aspx"
    ),
    "mra": lambda m: fetch_page_and_linked_pdfs(
        m, "mra_competitions", "https://maharifle.com/competitions", pdf_exclude=["shotgun", "relay", "/notices/"]
    ),
    "sgfi": lambda m: fetch_serpapi_source(
        m, "sgfi_search", "School Games Federation of India shooting rifle competition 2026"
    ),
    "issf": lambda m: fetch_simple_page(
        m, "issf_calendar", "https://www.issf-sports.org/calendar"
    ),
    "asc": lambda m: fetch_simple_page(
        m, "asc_homepage", "https://www.asia-shooting.org/"
    ),
}

YEARLY_SWEEP_SOURCES = {
    "nrai_next_year": lambda m: fetch_serpapi_source(
        m, "nrai_2027_calendar_sweep", "NRAI 2027 tentative calendar rifle pistol events"
    ),
    "mra_next_year": lambda m: fetch_serpapi_source(
        m, "mra_2027_calendar_sweep", "Maharashtra Rifle Association 2027 calendar competitions"
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Fetch only this source key")
    parser.add_argument("--list", action="store_true", help="List available source keys")
    parser.add_argument("--yearly-sweep", action="store_true", help="Also run the weekly next-year-calendar sweep")
    args = parser.parse_args()

    all_sources = {**DAILY_SOURCES, **YEARLY_SWEEP_SOURCES}

    if args.list:
        for key in DAILY_SOURCES:
            print(f"{key}  (daily)")
        for key in YEARLY_SWEEP_SOURCES:
            print(f"{key}  (yearly-sweep only)")
        return 0

    if not FIRECRAWL_KEY or not SERPAPI_KEY:
        print("ERROR: FIRECRAWL_API_KEY and/or SERPAPI_API_KEY missing from .env", file=sys.stderr)
        return 1

    manifest = []

    if args.source:
        if args.source not in all_sources:
            print(f"Unknown source '{args.source}'. Use --list to see options.", file=sys.stderr)
            return 1
        print(f"Fetching source: {args.source}")
        all_sources[args.source](manifest)
    else:
        for key, fn in DAILY_SOURCES.items():
            print(f"Fetching source: {key}")
            fn(manifest)
        if args.yearly_sweep:
            for key, fn in YEARLY_SWEEP_SOURCES.items():
                print(f"Fetching source: {key}")
                fn(manifest)

    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    ok = sum(1 for m in manifest if m["status"] == "ok")
    failed = [m for m in manifest if m["status"] != "ok"]
    print(f"\nFetched {ok}/{len(manifest)} items. Manifest: {os.path.relpath(MANIFEST_PATH, PROJECT_ROOT)}")
    for m in failed:
        print(f"  FAILED: {m['source']} ({m['url']}) -> {m['status']}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
