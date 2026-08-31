"""Merge freshly-extracted competition/camp records into the persistent
state/ store (Phase 4: Dedup). Pure local JSON read/write — no network calls,
no paid APIs.

Each run of the pipeline is: fetch_sources.py (Firecrawl/SerpAPI) -> agent
extraction (writes .tmp/extracted_competitions.json and
.tmp/extracted_training_camps.json) -> this tool (merges into state/).

Merge rule per record:
  1. Exact id match against state/: overwrite all fields EXCEPT
     first_seen_date, reminders_sent (competitions), and notified (camps) —
     those carry the send-history and must never be reset by a re-scrape.
     last_seen_date is bumped to today.
  2. No exact id match: fall back to fuzzy matching (name-token overlap +
     date proximity, see fuzzy_match.py) against existing state/ records not
     already claimed this run. This matters because the id is partly derived
     from name+source_url, and either can drift between runs — e.g. a
     source's PDF filename changes, an event gets renamed, or (as happened
     once already) the extraction *method* itself changes. Without this, a
     drifted id would create a duplicate record and re-send an
     already-delivered event as "new" — a real duplicate-email bug, not a
     hypothetical one.
  3. No match at all: genuinely new record, inserted with fresh
     first_seen_date/last_seen_date = today, reminders_sent = [] /
     notified = false.

Usage:
    python tools/merge_records.py
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuzzy_match import same_event

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")
STATE_DIR = os.path.join(PROJECT_ROOT, "state")

TODAY = date.today().isoformat()

PRESERVE_FIELDS_COMPETITIONS = {"first_seen_date", "reminders_sent"}
PRESERVE_FIELDS_CAMPS = {"first_seen_date", "notified"}


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def merge(extracted: dict, existing: dict, preserve_fields: set) -> tuple:
    new_count = 0
    updated_count = 0
    fuzzy_matched_count = 0
    claimed_existing_ids = set()

    for rid, record in extracted.items():
        target_id = None

        if rid in existing:
            target_id = rid
        else:
            # Fuzzy fallback: does this extracted record actually match an
            # existing state record under a different id?
            for existing_id, existing_record in existing.items():
                if existing_id in claimed_existing_ids:
                    continue  # already matched to a different extracted record this run
                if same_event(record["name"], record["date_start"], record["date_end"],
                               existing_record["name"], existing_record["date_start"], existing_record["date_end"]):
                    target_id = existing_id
                    fuzzy_matched_count += 1
                    break

        if target_id:
            preserved = {k: existing[target_id][k] for k in preserve_fields if k in existing[target_id]}
            merged = {**record, **preserved, "id": target_id, "last_seen_date": TODAY}
            existing[target_id] = merged
            claimed_existing_ids.add(target_id)
            updated_count += 1
        else:
            record["first_seen_date"] = TODAY
            record["last_seen_date"] = TODAY
            for field in preserve_fields:
                if field not in record:
                    record[field] = [] if field == "reminders_sent" else (False if field == "notified" else TODAY)
            existing[rid] = record
            new_count += 1

    if fuzzy_matched_count:
        print(f"  (of which {fuzzy_matched_count} matched an existing record by name/date rather than exact id)")
    return existing, new_count, updated_count


def main():
    extracted_comp_path = os.path.join(TMP_DIR, "extracted_competitions.json")
    extracted_camp_path = os.path.join(TMP_DIR, "extracted_training_camps.json")
    state_comp_path = os.path.join(STATE_DIR, "competitions.json")
    state_camp_path = os.path.join(STATE_DIR, "training_camps.json")

    extracted_comps = load_json(extracted_comp_path, {})
    extracted_camps = load_json(extracted_camp_path, {})

    if not extracted_comps and not extracted_camps:
        print(f"No extracted records found at {extracted_comp_path} or {extracted_camp_path}. Nothing to merge.")
        return 0

    state_comps = load_json(state_comp_path, {})
    state_camps = load_json(state_camp_path, {})

    state_comps, comp_new, comp_updated = merge(extracted_comps, state_comps, PRESERVE_FIELDS_COMPETITIONS)
    state_camps, camp_new, camp_updated = merge(extracted_camps, state_camps, PRESERVE_FIELDS_CAMPS)

    save_json(state_comp_path, state_comps)
    save_json(state_camp_path, state_camps)

    print(f"Competitions: {comp_new} new, {comp_updated} updated (last_seen_date -> {TODAY}). Total in state: {len(state_comps)}")
    print(f"Training camps: {camp_new} new, {camp_updated} updated. Total in state: {len(state_camps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
