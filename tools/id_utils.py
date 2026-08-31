"""Shared dedup-key hashing, per the schema in workflows/scan_rifle_competitions.md.

id = sha1(normalize(name) + date_start + source_domain), truncated to 16 hex chars.
Used both during extraction (to assign ids to newly-extracted records) and by
the Phase 4 merge/dedup tool (to check a record against state/*.json).
"""
import hashlib
import re
from urllib.parse import urlparse


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def source_domain(source_url: str) -> str:
    return urlparse(source_url).netloc.lower()


def compute_id(name: str, date_start: str, source_url: str) -> str:
    key = f"{normalize(name)}|{date_start}|{source_domain(source_url)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
