"""Shared fuzzy-matching logic for recognizing "the same real-world event"
across different names/dates/sources. Used by:
  - extract_deterministic.py: cross-source dedup (NRAI vs ISSF vs MRA naming
    the same event slightly differently)
  - merge_records.py: matching a freshly-extracted record against an existing
    state/ record even when its id doesn't match exactly (e.g. after a
    source's PDF filename changes, or after switching extraction method)

Two events are considered the same only if their names overlap enough AND
their dates are close AND they don't disagree on a hard discriminator
(discipline, zone) — see _hard_conflict for why plain word-overlap alone is
not safe (e.g. "13th West Zone Championship Rifle" vs "45th North Zone
Championship Rifle" share 4 of 8 words from template boilerplate alone).
"""
import re
from datetime import date as _date

DEDUP_STOPWORDS = {"IN", "THE", "OF", "EVENTS", "EVENT", "NR", "AT", "FOR", "AND"}
DISCIPLINE_WORDS = ["RIFLE", "PISTOL", "SHOTGUN"]
# Order matters: "NORTH EAST ZONE" must be checked before "NORTH ZONE"/"EAST
# ZONE" so it isn't double-counted as belonging to both.
ZONE_WORDS = ["NORTH EAST ZONE", "WEST ZONE", "NORTH ZONE", "SOUTH ZONE", "EAST ZONE"]

MATCH_OVERLAP_THRESHOLD = 0.5
DATE_TOLERANCE_DAYS = 3


def normalize_tokens(name: str) -> set:
    cleaned = re.sub(r"[^\w\s]", " ", name.upper())
    return {t for t in cleaned.split() if t not in DEDUP_STOPWORDS and len(t) > 1}


def dates_close(s1, e1, s2, e2, tolerance_days=DATE_TOLERANCE_DAYS) -> bool:
    if not s1 or not s2:
        return False
    e1, e2 = e1 or s1, e2 or s2
    try:
        d1s, d1e = _date.fromisoformat(s1), _date.fromisoformat(e1)
        d2s, d2e = _date.fromisoformat(s2), _date.fromisoformat(e2)
    except ValueError:
        return False
    if d1s <= d2e and d2s <= d1e:
        return True
    gap = min(abs((d1s - d2e).days), abs((d2s - d1e).days))
    return gap <= tolerance_days


def _tags_present(text: str, vocabulary: list) -> set:
    upper = text.upper()
    found = set()
    remaining = upper
    for word in vocabulary:
        if word in remaining:
            found.add(word)
            remaining = remaining.replace(word, "")
    return found


def hard_conflict(name1: str, name2: str) -> bool:
    """True if both names assign a tag from the same discriminator category
    (discipline or zone) and those tags differ. Silent (False) when a name
    doesn't mention the category at all — absence of information should
    never block a match, only an actual disagreement should."""
    for vocabulary in (DISCIPLINE_WORDS, ZONE_WORDS):
        tags1 = _tags_present(name1, vocabulary)
        tags2 = _tags_present(name2, vocabulary)
        if tags1 and tags2 and tags1.isdisjoint(tags2):
            return True
    return False


def same_event(name1, date_start1, date_end1, name2, date_start2, date_end2) -> bool:
    tokens1, tokens2 = normalize_tokens(name1), normalize_tokens(name2)
    union = tokens1 | tokens2
    overlap = len(tokens1 & tokens2) / max(1, len(union))
    return (
        overlap >= MATCH_OVERLAP_THRESHOLD
        and not hard_conflict(name1, name2)
        and dates_close(date_start1, date_end1, date_start2, date_end2)
    )
