"""Date parsing helpers for deterministic extraction (Phase 5).

Sources use inconsistent date formats — this module normalizes the ones
actually observed in Phase 3 raw data:
  - "07 Sep - 13 Sep 2026" / "29 Aug - 30 Aug 2026" (MRA listing page)
  - "13TH TO 17TH JULY 2026" / "17TH AUGUST TO 2ND SEPTEMBER 2026" (NRAI PDF tables)
  - "18th August, 2026" / "23.04.2026" (MRA circular free text)
"""
import difflib
import re

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_FULL_MONTH_NAMES = [k for k in MONTHS if len(k) > 4]  # for fuzzy-matching typos


def lookup_month(name: str):
    """Exact lookup, falling back to fuzzy match for source typos — e.g. the
    real NRAI 2026 calendar PDF contains "SEPTMEBER" (transposed letters)."""
    name = name.lower()
    if name in MONTHS:
        return MONTHS[name]
    close = difflib.get_close_matches(name, _FULL_MONTH_NAMES, n=1, cutoff=0.75)
    return MONTHS[close[0]] if close else None

ORDINAL_RE = re.compile(r"(\d{1,2})(?:ST|ND|RD|TH|st|nd|rd|th)", re.IGNORECASE)


def strip_ordinals(text: str) -> str:
    return ORDINAL_RE.sub(r"\1", text)


def to_iso(day: int, month: int, year: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


# Matches "7 Sep 2026", "07 September 2026", "7.9.2026", "07.09.2026"
_TEXT_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\s*,?\s*(\d{4})"
)
_NUMERIC_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")


def parse_single_date(text: str):
    """Parse one date mention. Returns ISO string or None."""
    text = strip_ordinals(text).strip()
    m = _NUMERIC_DATE_RE.search(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return to_iso(day, month, year)
    m = _TEXT_DATE_RE.search(text)
    if m:
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = lookup_month(month_name)
        if month:
            return to_iso(day, month, year)
    return None


# "13TH TO 17TH JULY 2026" / "07 Sep - 13 Sep 2026" / "17 AUGUST TO 2 SEPTEMBER 2026"
_RANGE_RE = re.compile(
    r"(\d{1,2})\s*(?:ST|ND|RD|TH)?\s*(?:-|TO|–|—)\s*(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Za-z]+)\s*,?\s*(\d{4})",
    re.IGNORECASE,
)
# "17 AUGUST TO 2 SEPTEMBER 2026" — cross-month, both months named
_RANGE_CROSS_MONTH_RE = re.compile(
    r"(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Za-z]+)\s*(?:-|TO|–|—)\s*(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Za-z]+)\s*,?\s*(\d{4})",
    re.IGNORECASE,
)


def parse_date_range(text: str):
    """Returns (date_start, date_end) as ISO strings, either may be None."""
    if not text or "TBD" in text.upper():
        return None, None
    text = text.strip()

    m = _RANGE_CROSS_MONTH_RE.search(text)
    if m:
        d1, mo1, d2, mo2, year = m.groups()
        month1 = lookup_month(mo1)
        month2 = lookup_month(mo2)
        if month1 and month2:
            return to_iso(int(d1), month1, int(year)), to_iso(int(d2), month2, int(year))

    m = _RANGE_RE.search(text)
    if m:
        d1, d2, mo, year = m.groups()
        month = lookup_month(mo)
        if month:
            return to_iso(int(d1), month, int(year)), to_iso(int(d2), month, int(year))

    # Single date, no range
    single = parse_single_date(text)
    if single:
        return single, None

    return None, None
