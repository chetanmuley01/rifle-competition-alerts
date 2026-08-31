"""Verify FIRECRAWL_API_KEY and SERPAPI_API_KEY from .env are valid.

Usage: python tools/check_api_keys.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def mask(key: str) -> str:
    if not key:
        return "(missing)"
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***"


def check_firecrawl(key: str) -> tuple[bool, str]:
    if not key:
        return False, "no key set"
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {key}"},
            json={"url": "https://example.com", "formats": ["markdown"]},
            timeout=30,
        )
    except requests.RequestException as e:
        return False, f"request failed: {e}"
    if resp.status_code == 200:
        return True, "200 OK — scraped example.com"
    if resp.status_code in (401, 403):
        return False, f"{resp.status_code} — key rejected"
    return False, f"{resp.status_code} — {resp.text[:200]}"


def check_serpapi(key: str) -> tuple[bool, str]:
    if not key:
        return False, "no key set"
    try:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={"q": "test", "api_key": key, "engine": "google", "num": 1},
            timeout=30,
        )
    except requests.RequestException as e:
        return False, f"request failed: {e}"
    if resp.status_code == 200:
        data = resp.json()
        if "error" in data:
            return False, f"200 but error field: {data['error']}"
        return True, "200 OK — search returned results"
    if resp.status_code in (401, 403):
        return False, f"{resp.status_code} — key rejected"
    return False, f"{resp.status_code} — {resp.text[:200]}"


def main() -> int:
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    serpapi_key = os.environ.get("SERPAPI_API_KEY", "")

    all_ok = True
    for name, key, check_fn in [
        ("FIRECRAWL_API_KEY", firecrawl_key, check_firecrawl),
        ("SERPAPI_API_KEY", serpapi_key, check_serpapi),
    ]:
        ok, detail = check_fn(key)
        status = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"[{status}] {name} ({mask(key)}): {detail}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
