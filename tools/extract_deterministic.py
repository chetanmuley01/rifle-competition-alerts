"""Deterministic (non-LLM) extraction for Phase 5's unattended daily run.

Replaces the agent-judgment extraction used in Phase 3 for the automated
path, per the user's explicit choice (zero Claude involvement in the
scheduled run, so cost = Firecrawl/SerpAPI only, fully known).

Reliable, pattern-based parsers exist for:
  - NRAI PDF calendars (clean markdown tables) -> competitions + camps
  - ISSF calendar (structurally consistent HTML->markdown) -> competitions + camps
  - MRA competitions listing page (structured card format) -> competitions

Best-effort (lower confidence) regex parsing for:
  - MRA per-competition circular PDFs (free text — deadline/eligibility only
    extracted when a known phrasing matches; left blank rather than guessed
    wrong otherwise)

NOT auto-extracted (too unstructured to parse reliably without judgment):
  - ASC homepage, SGFI search results — flagged into
    .tmp/needs_manual_review.md instead of risking wrong structured data.

Reads .tmp/fetch_manifest.json (written by fetch_sources.py) and the raw
files it points to. Writes .tmp/extracted_competitions.json and
.tmp/extracted_training_camps.json in the same format the Phase 3 agent
extraction used, so tools/merge_records.py works unchanged.

Usage:
    python tools/extract_deterministic.py
"""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from date_utils import parse_date_range
from id_utils import compute_id
from fuzzy_match import same_event

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
MANIFEST_PATH = os.path.join(TMP_DIR, "fetch_manifest.json")

TODAY = date.today().isoformat()

SKIP_KEYWORDS = [
    "JUDGES COURSE", "COACHES COURSE", "REFEREE COURSE", "EST COURSE",
    "SELECTION TRIAL", "NATIONAL SQUAD CAMP",  # squad camp handled separately as a camp, not via this skip list catch-all text match below for competitions
]

MD_ESCAPE_RE = re.compile(r"\\([\[\]\\*_`])")


def unescape_markdown(text: str) -> str:
    """Firecrawl's markdown escapes [, ], etc. — e.g. '\\[MAFC 2026/2\\]'.
    Names/venues are display text, not real markdown, so unescape them."""
    return MD_ESCAPE_RE.sub(r"\1", text) if text else text


def is_past(date_start, date_end) -> bool:
    """A record with unknown dates is kept (can't tell if it's past) — only
    filter out records confirmed to have already ended before today."""
    effective_end = date_end or date_start
    if not effective_end:
        return False
    return effective_end < TODAY


def is_shotgun_only(text: str) -> bool:
    upper = text.upper()
    return "SHOTGUN" in upper and "RIFLE" not in upper and "PISTOL" not in upper and "ALL DISCIPLINES" not in upper


def is_admin_course_or_trial(text: str) -> bool:
    """Excludes items that aren't athlete-facing at all: officiating/judging
    courses, coaching admin courses, internal team-selection trials, and
    governance meetings (e.g. ISSF General Assembly is not a competition)."""
    upper = text.upper()
    return any(kw in upper for kw in [
        "JUDGES COURSE", "COACHES COURSE", "REFEREE COURSE", "EST COURSE",
        "SELECTION TRIAL", "TRIALS", "GENERAL ASSEMBLY", "CONGRESS", "BOARD MEETING",
    ])


def is_camp_like(text: str) -> bool:
    upper = text.upper()
    return "CAMP" in upper or "ACADEMY" in upper


def guess_entry_path(name: str, remarks: str = "") -> str:
    combined = f"{name} {remarks}".upper()
    if "TEAM TO BE SELECTED" in combined or "SELECTED VIA" in combined or "SQUAD" in combined:
        return "federation-selection"
    if any(kw in combined for kw in ["WORLD CUP", "WORLD CHAMPIONSHIP", "ASIAN GAMES", "ASIAN CHAMPIONSHIP", "OLYMPIC"]):
        return "federation-selection"
    if "ACADEMY" in combined or "ONLINE" in combined:
        return "unclear"
    return "unclear"


def guess_level(name: str, venue: str, default: str = "national") -> str:
    combined = f"{name} {venue}".upper()
    international_markers = ["ASIAN GAMES", "ISSF", "WORLD CUP", "WORLD CHAMPIONSHIP", "ASIAN CHAMPIONSHIP", "OLYMPIC"]
    if any(m in combined for m in international_markers):
        return "international"
    if any(z in combined for z in ["WEST ZONE", "NORTH ZONE", "SOUTH ZONE", "EAST ZONE", "NORTH EAST ZONE", "NATIONAL", "NSCC", "AIGVMSC"]):
        return "national"
    return default


def build_record_id(name, date_start, source_url):
    return compute_id(name, date_start or "unknown", source_url)


# ---------------------------------------------------------------------------
# NRAI PDF table parser
# ---------------------------------------------------------------------------
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def extract_nrai_pdf_table(markdown: str, source_url: str, source_name: str):
    competitions, camps = [], []
    for line in markdown.splitlines():
        m = TABLE_ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 4:
            continue
        # Skip header/separator rows
        if cells[0].upper() in ("S.NO.", "---", "") and not cells[0].isdigit():
            if cells[0] != "" or not cells[1].isdigit():
                continue
        if not re.match(r"^\d+$", cells[0]):
            continue

        dates_text = cells[1] if len(cells) > 1 else ""
        particulars = unescape_markdown(cells[2] if len(cells) > 2 else "")
        venue = unescape_markdown(cells[3] if len(cells) > 3 else "")
        remarks = cells[4] if len(cells) > 4 else ""

        if not particulars or is_shotgun_only(particulars) or is_admin_course_or_trial(particulars):
            continue

        date_start, date_end = parse_date_range(dates_text)
        if is_past(date_start, date_end):
            continue
        rid = build_record_id(particulars, date_start, source_url)
        base = {
            "id": rid, "name": particulars,
            "date_start": date_start, "date_end": date_end,
            "location": {"venue": venue or None, "city": None, "state": None, "country": "India"},
            "entry_path": guess_entry_path(particulars, remarks),
            "source_name": source_name, "source_url": source_url,
            "status": "tentative", "confidence": "medium",
            "first_seen_date": TODAY, "last_seen_date": TODAY,
        }
        if is_camp_like(particulars):
            base.update({
                "hosting_body": "National Rifle Association of India (NRAI)",
                "discipline_focus": "Rifle/Pistol",
                "coaches": [], "participation_criteria": remarks or None,
                "application_process": None, "notified": False,
            })
            camps.append(base)
        else:
            base.update({
                "level": guess_level(particulars, venue),
                "discipline": "Rifle/Pistol",
                "registration_deadline": None,
                "eligibility": {"age_category": None, "gender_category": None, "membership_required": None, "notes": remarks or None},
                "organizing_body": "National Rifle Association of India (NRAI)",
                "reminders_sent": [],
            })
            competitions.append(base)
    return competitions, camps


# ---------------------------------------------------------------------------
# ISSF calendar parser
# ---------------------------------------------------------------------------
ISSF_EVENT_RE = re.compile(r"\[(.*?)\]\((https://www\.issf-sports\.org/competitions/\d+)\)", re.DOTALL)
IMG_MD_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)")


def extract_issf_calendar(markdown: str, source_url: str, source_name: str):
    competitions, camps = [], []
    for match in ISSF_EVENT_RE.finditer(markdown):
        inner, url = match.group(1), match.group(2)
        parts = [p.strip() for p in inner.split("\\") if p.strip()]
        if len(parts) < 3:
            continue
        date_text, name, location_raw = parts[0], unescape_markdown(parts[1]), parts[2]
        location = unescape_markdown(IMG_MD_RE.sub("", location_raw).strip())

        if is_shotgun_only(name) or is_admin_course_or_trial(name):
            continue

        date_start, date_end = parse_date_range(date_text)
        if is_past(date_start, date_end):
            continue
        rid = build_record_id(name, date_start, url)
        base = {
            "id": rid, "name": name,
            "date_start": date_start, "date_end": date_end,
            "location": {"venue": None, "city": location or None, "state": None, "country": None},
            "entry_path": guess_entry_path(name),
            "source_name": source_name, "source_url": url,
            "status": "confirmed", "confidence": "medium",
            "first_seen_date": TODAY, "last_seen_date": TODAY,
        }
        if is_camp_like(name):
            base.update({
                "hosting_body": "ISSF", "discipline_focus": "All disciplines",
                "coaches": [], "participation_criteria": None,
                "application_process": None, "notified": False,
            })
            camps.append(base)
        else:
            base.update({
                "level": "international", "discipline": "Rifle/Pistol/Shotgun" if "SHOTGUN" in name.upper() else "Rifle/Pistol",
                "registration_deadline": None,
                "eligibility": {"age_category": None, "gender_category": None, "membership_required": None, "notes": None},
                "organizing_body": "ISSF",
                "reminders_sent": [],
            })
            competitions.append(base)
    return competitions, camps


# ---------------------------------------------------------------------------
# MRA competitions listing page parser
# ---------------------------------------------------------------------------
MRA_CARD_RE = re.compile(
    r"###\s+(.+?)\n+\[Circular\]\((https://[^\)\s]+?\.pdf)[^\)]*\)\n+"
    r"\*\*Date:\*\*\s*(.+?)\*\*Location:\*\*\s*(.+?)\n+(\w+)",
)


def extract_mra_listing(markdown: str, source_name: str):
    competitions = []
    for match in MRA_CARD_RE.finditer(markdown):
        name, circular_url, dates_text, location, status_word = match.groups()
        name = unescape_markdown(name.strip())
        location = unescape_markdown(location)
        if is_shotgun_only(name):
            continue
        date_start, date_end = parse_date_range(dates_text)
        if is_past(date_start, date_end):
            continue
        rid = build_record_id(name, date_start, circular_url)
        competitions.append({
            "id": rid, "name": name,
            "level": guess_level(name, location, default="state"), "discipline": "10m Air Rifle" if "AIR" in name.upper() else "Rifle",
            "location": {"venue": location.strip() or None, "city": None, "state": "Maharashtra", "country": "India"},
            "date_start": date_start, "date_end": date_end,
            "registration_deadline": None,
            "eligibility": {"age_category": None, "gender_category": None, "membership_required": None, "notes": None},
            "entry_path": "unclear",
            "organizing_body": "Maharashtra Rifle Association",
            "source_name": source_name, "source_url": circular_url,
            "status": "confirmed" if status_word.lower() == "confirmed" else "tentative",
            "confidence": "medium",
            "first_seen_date": TODAY, "last_seen_date": TODAY,
            "reminders_sent": [],
            "_circular_url": circular_url,  # internal use: matched against circular detail files below
        })
    return competitions


# ---------------------------------------------------------------------------
# MRA circular detail enrichment (best-effort, regex on free text)
# ---------------------------------------------------------------------------
DEADLINE_PHRASE_RE = re.compile(
    r"last date[s]?\s+(?:of|for)\s+(?:receipt of entries|accepting entries)[^.]{0,120}?"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}|\d{1,2}[./]\d{1,2}[./]\d{4})",
    re.IGNORECASE,
)


def extract_mra_circular_deadline(markdown: str):
    """Best-effort only. Returns ISO date string or None — never guesses."""
    from date_utils import parse_single_date
    m = DEADLINE_PHRASE_RE.search(markdown)
    if not m:
        return None
    return parse_single_date(m.group(1))


# ---------------------------------------------------------------------------
# Cross-source dedup: the same real event is often described slightly
# differently by different sources (NRAI's calendar, ISSF's calendar, MRA's
# listing all named/dated "20th Asian Games" a bit differently) — per-source
# id hashing alone can't catch that, so this groups by name-token overlap +
# date proximity (see fuzzy_match.py) and keeps one representative per group.
# ---------------------------------------------------------------------------
def dedup_cross_source(records: list, source_priority: list) -> list:
    def priority(rec):
        for i, p in enumerate(source_priority):
            if p in rec["source_name"]:
                return i
        return len(source_priority)

    groups = []
    for rec in records:
        placed = False
        for group in groups:
            rep = group[0]
            if same_event(rec["name"], rec["date_start"], rec["date_end"], rep["name"], rep["date_start"], rep["date_end"]):
                group.append(rec)
                placed = True
                break
        if not placed:
            groups.append([rec])

    return [sorted(group, key=priority)[0] for group in groups]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"{MANIFEST_PATH} not found — run tools/fetch_sources.py first.")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def read_raw(rel_path):
    if not rel_path:
        return ""
    full = os.path.join(PROJECT_ROOT, rel_path)
    if not os.path.exists(full):
        return ""
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def main():
    manifest = load_manifest()

    all_competitions = {}
    all_camps = {}
    review_needed = []

    # Index circular-detail files fetched as children of the MRA listing, by URL suffix
    circular_texts_by_url = {}
    for item in manifest:
        if item["status"] == "ok" and "linked circular" in item["source"] and "mra" in item["source"].lower():
            circular_texts_by_url[item["url"]] = read_raw(item["file"])

    for item in manifest:
        if item["status"] != "ok":
            continue
        source = item["source"]
        content = read_raw(item["file"])
        if not content:
            continue

        if source.startswith("nrai_calendar_page") and "linked circular" in source:
            # One of the followed PDF calendar links (source is literally
            # "nrai_calendar_page (linked circular)" — not an exact match on
            # the base name, which is why this routing missed every NRAI PDF
            # on the first pass).
            comps, camps = extract_nrai_pdf_table(content, item["url"], "NRAI Calendar")
            for c in comps:
                all_competitions[c["id"]] = c
            for c in camps:
                all_camps[c["id"]] = c
        elif source == "issf_calendar":
            comps, camps = extract_issf_calendar(content, item["url"], "ISSF Calendar")
            for c in comps:
                all_competitions[c["id"]] = c
            for c in camps:
                all_camps[c["id"]] = c
        elif source == "mra_competitions":
            comps = extract_mra_listing(content, "Maharashtra Rifle Association")
            for c in comps:
                circular_text = circular_texts_by_url.get(c["_circular_url"], "")
                if circular_text:
                    deadline = extract_mra_circular_deadline(circular_text)
                    if deadline:
                        c["registration_deadline"] = deadline
                        c["confidence"] = "medium"
                    else:
                        c["confidence"] = "low"
                del c["_circular_url"]
                all_competitions[c["id"]] = c
        elif source in ("asc_homepage", "sgfi_search") or "asc" in source.lower():
            review_needed.append((source, item["url"], item["file"]))

    # Cross-source dedup — priority order determines which version of a
    # duplicate event is kept: ISSF is authoritative for international dates,
    # MRA's listing carries the real registration deadline for MH state
    # events, NRAI's own calendar is the fallback (it pads dates with
    # travel/camp time around the actual competition, so it's less precise).
    source_priority = ["ISSF Calendar", "Maharashtra Rifle Association", "NRAI Calendar"]
    before_comp, before_camp = len(all_competitions), len(all_camps)
    deduped_competitions = dedup_cross_source(list(all_competitions.values()), source_priority)
    deduped_camps = dedup_cross_source(list(all_camps.values()), source_priority)
    all_competitions = {c["id"]: c for c in deduped_competitions}
    all_camps = {c["id"]: c for c in deduped_camps}
    if before_comp != len(all_competitions) or before_camp != len(all_camps):
        print(f"Cross-source dedup: {before_comp} -> {len(all_competitions)} competitions, {before_camp} -> {len(all_camps)} camps.")

    comp_path = os.path.join(TMP_DIR, "extracted_competitions.json")
    camp_path = os.path.join(TMP_DIR, "extracted_training_camps.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(all_competitions, f, indent=2)
    with open(camp_path, "w", encoding="utf-8") as f:
        json.dump(all_camps, f, indent=2)

    if review_needed:
        review_path = os.path.join(TMP_DIR, "needs_manual_review.md")
        with open(review_path, "w", encoding="utf-8") as f:
            f.write("# Sources not auto-extracted (too unstructured for reliable regex parsing)\n\n")
            f.write("Check these manually for anything new — ASC and SGFI content is free-form "
                    "(news items, mixed cards) and isn't parsed into structured records.\n\n")
            for source, url, file in review_needed:
                f.write(f"- **{source}**: {url} (raw: `{file}`)\n")
        print(f"Flagged {len(review_needed)} unstructured sources for manual review: {os.path.relpath(review_path, PROJECT_ROOT)}")

    print(f"Extracted {len(all_competitions)} competitions, {len(all_camps)} training camps (deterministic parsing).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
