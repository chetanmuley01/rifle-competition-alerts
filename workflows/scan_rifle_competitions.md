# Workflow: Scan Rifle Shooting Competitions (Daily)

> Status: **draft — Phase 1 (Requirements & Source Discovery)**. This workflow will be filled in as Phase 2 (schema), Phase 3 (fetch + extract), and Phase 4 (dedup + tips + email) are built. See `rifle-competition-alerts-project.md` in the project root for the full build plan.

## Objective
Scan known sources daily for open rifle shooting competitions and training camps — state/national/international level, 10m air rifle and other rifle disciplines — that Rutuja may be eligible for or should be aware of, and produce a structured list of new/updated listings for the daily email digest.

## Cost control (locked 2026-08-31 — read before running any tool here)
- **Firecrawl and SerpAPI cost real money per call.** Do not run `tools/fetch_sources.py` (or make any other Firecrawl/SerpAPI call) without the user's explicit go-ahead for that specific run. Never assume it's fine because a past run was approved.
- **Phase 4 (dedup/merge, tips, email) is built to require zero paid APIs** — it only reads/writes local JSON in `.tmp/` and `state/`, plus free Gmail SMTP for sending. If a future change to these tools would introduce a paid API call, flag it to the user before building it, don't default into it.
- **Any future scheduled/automated run (Phase 5)** must have its recurring paid-API cost (call volume × frequency) explicitly approved by the user before being wired up — a cron/n8n job firing Firecrawl/SerpAPI calls daily is a real recurring cost, not a one-time approval.
- **Never call the Anthropic API with a raw API key** (metered, billed separately from a Pro/Max subscription) for any part of this pipeline. The extraction step is agent judgment performed inside an already-running Claude Code session, not a scripted API call — keep it that way.

## Locked decisions (Phase 1)
- **Recipient:** chetanmuley01@gmail.com
- **Scope:** National bodies (NRAI, School Games Federation) + Maharashtra state-level + **international bodies (ISSF, Asian Shooting Confederation)**, to start. Expand states in Phase 6.
- **APIs:** Firecrawl (page/PDF → clean markdown, for the LLM extraction step) + SerpAPI (search-based discovery for scattered/uncalendared announcements)
- **International events:** tracked for awareness, not necessarily direct entry — each listing gets an `entry_path` field (`federation-selection` / `open-entry` / `unclear`) since most ISSF/Asian-level competitions are entered via national-federation nomination, not individual sign-up.
- **Training camps:** tracked as their **own category**, separate from competitions, with their own fields (camp name, dates, location, hosting body, discipline/coaching focus, application process, link) — not mixed into the competitions list.

## Verified sources

| Source | URL | Format | Notes |
|---|---|---|---|
| National Rifle Association of India (NRAI) | https://www.thenrai.in/ | PDF calendars + `news_events_details.aspx` | Calendars are compressed-stream PDFs — plain text extraction (naive fetch, no PDF library) fails. Must go through Firecrawl's PDF handling or a real PDF text library (e.g. pdfplumber/PyMuPDF), not raw text scraping. |
| Maharashtra Rifle Association | https://maharifle.com/competitions | Server-side rendered HTML card list | Gives name, dates, venue, status. Does **not** include eligibility/deadline/entry fee. |
| — per-competition circulars | linked from each card, e.g. `maharifle.org/file/{id}/pdf` (note: `.org` domain hosts legacy circular PDFs, `.com` is the active site) | PDF | Same PDF-parsing caveat as NRAI. This is where eligibility, deadline, and fee actually live — the extraction step must open these, not just the calendar page. |
| Maharashtra Rifle Association news | https://maharifle.com/news | HTML list | Mostly links out to third-party news coverage rather than official notices. Lower priority source. |
| School Games Federation of India | https://sgfi.org.in/ | No structured calendar found yet | Confirmed active (69th National School Games 2025-26 shooting events). Needs a SerpAPI-driven discovery pass in Phase 3 rather than direct scraping. |
| International Shooting Sport Federation (ISSF) | https://www.issf-sports.org/calendar | Static HTML calendar, no JS required | Gives event name, dates, location, competition type (World Cups, World/Junior Championships, etc.). **No eligibility/entry info on the list page** — must open individual event pages. Discipline distinguishable from title keywords ("Rifle", "Pistol", "10m", etc.). |
| Asian Shooting Confederation (ASC) | https://www.asia-shooting.org/ | HTML site with Calendar/Competitions nav section | Confirmed both **competitions** (20th Asian Games — Nagoya, Sep–Oct 2026; Asian Rifle/Pistol Championship 2027 — New Delhi, 2028 — Shymkent, with Olympic quota counts) and **training camps** (14th Asian Youth Training & Coaching Camp — Doha, Jan 2026; ISSF Academy C Course, Sep 2026). This is the primary source for the new Training Camps category. |
| NRAI elite/national camp announcements | via https://www.thenrai.in/ news/circulars | HTML/PDF news items | India-hosted but internationally-staffed camps (e.g. the 2026 elite National Camp used foreign coaches Peter Wilson, Thomas Farnik, Jalena Arunovic, Riccardo Filippelli) — counts as a Training Camps listing even though sourced from NRAI, not ISSF/ASC. |

## Known pitfalls (learned in Phase 1 research)
- **Do not attempt naive PDF text extraction** (plain WebFetch, no library) on NRAI or MRA circulars — confirmed to fail (compressed FlateDecode streams). Use Firecrawl or a real PDF parser.
- Competition **level/eligibility/deadline is often not on the calendar/listing page** — it's inside a linked circular PDF per event. The fetcher needs to follow those links, not just scrape the summary card.
- MRA's `.org` and `.com` domains serve different purposes (`.org` = legacy file host for circulars, `.com` = current site with competitions/news pages) — don't assume they're interchangeable or that one is deprecated.
- **Most ISSF/Asian-level competitions are entered by national-federation nomination, not individual registration** — don't present these the same way as an open club/district meet. Always populate `entry_path` so the email is honest about what Rutuja can act on directly.
- **Firecrawl rate limit (learned 2026-08-31, Phase 3):** firing scrape requests back-to-back (e.g. following 15+ circular links in a row) triggers `429 Too Many Requests`. `tools/fetch_sources.py`'s `firecrawl_scrape()` now paces calls (~6.5s apart) and retries on 429 with backoff (respecting `Retry-After` when present). If this still trips on a larger source, increase `FIRECRAWL_PACING_SECONDS` rather than removing the pacing.
- **Markdown link parsing gotchas (Phase 3):** MRA's circular links use the `[text](url "title")` form (a quoted title after the URL) — a naive `\[.*\]\((url)\)` regex without an optional title group misses these entirely. Also, discipline (rifle vs. shotgun) is often only revealed *inside* the circular PDF, not in the link text or URL — don't rely on pre-fetch text filtering to fully separate rifle from shotgun circulars; treat that as the extraction step's job.

## Forward-visibility limitation (learned in Phase 1 research, 2026-08-31; corrected 2026-08-31 after Phase 3 fetcher testing)
Verified live against today's date (2026-08-31): the sources do **not** currently have a full 6–12 months of competitions published in advance.
- Maharashtra Rifle Association `/competitions` is a complete, unpaginated list — the furthest-out event on it is **13 Sep 2026** (~2 weeks out). Nothing for Oct–Dec 2026 exists there yet.
- **Correction:** the original Phase 1 check of NRAI's calendar used a naive PDF read that failed to extract content (compressed streams) and only saw document *metadata* (a revision date of 30.07.2026), leading to the wrong conclusion that NRAI's visibility stopped around July 2026. Once `tools/fetch_sources.py` actually pulled the PDF through Firecrawl (which parses it correctly into a clean markdown table), the **"TENTATIVE NRAI DOMESTIC CALENDAR (RIFLE/PISTOL/SHOTGUN EVENTS) – 2026"** document turned out to already list events through **11–31 Dec 2026** (69th NSCC) — i.e. NRAI already has ~4 months of forward visibility from today, not merely weeks. This source is more valuable than Phase 1 gave it credit for.
- No 2027 domestic calendar has been published by NRAI, MRA, or SGFI. Only two 2027 international fixtures are publicly known at all (Asian Rifle/Pistol Championships, Dec 2027; ISSF World Cup New Delhi, Apr 2027) — everything else 2027 simply doesn't exist at the source yet. This part of the original finding still holds.

**Revised conclusion:** national-level (NRAI) visibility already reaches ~4 months out (through end of 2026); state-level (MRA) visibility is much shorter (~2 weeks); nothing reaches into 2027 yet anywhere. **This remains a source-data limitation for the 2027 gap specifically, not a tooling gap** — but the tooling itself (naive fetch vs. Firecrawl) was the reason the *2026* visibility was undercounted. Lesson: don't trust a "can't extract" result as "data doesn't exist" — always re-verify with the real fetch tool before concluding a source is limited.

**Design implication (user-approved):** the daily/periodic scan is the right mechanism for this — it accumulates a rolling forward window over time and catches mid-year calendar revisions (e.g. the 30.07.2026 NRAI update). On top of the daily scan, Phase 3 must add a **weekly SerpAPI sweep** for "[federation] 2027 calendar" — style queries, so next year's calendar gets picked up the moment it's published rather than waiting to stumble onto it. This is a required Phase 3 deliverable, not optional polish.

## Pipeline (to be implemented — Phase 3/4)
1. **Fetch** — pull each source above via Firecrawl (HTML pages + linked PDFs) and SerpAPI (supplementary search for sources without a calendar page). Includes the weekly next-year-calendar sweep described above.
2. **Extract** — LLM-based extraction of raw text into structured fields. Two record types, schema TBD in full in Phase 2:
   - **Competitions**: name, level (state/national/international/open), discipline, location, date, deadline, eligibility, organizing body, `entry_path` (federation-selection/open-entry/unclear), link, source
   - **Training camps**: name, dates, location, hosting body, discipline/coaching focus, application process, link, source
3. **Dedup** — check against stored records (JSON/SQLite, TBD in Phase 2) before including in the digest — applies to both competitions and camps.
4. **Tips** — attach one rotating tip from the curated tips library.
5. **Email** — compose and send the daily digest with separate **Competitions** and **Training Camps** sections to the recipient above.

## Required environment variables (see `.env`)
- `FIRECRAWL_API_KEY`
- `SERPAPI_API_KEY`
- `DIGEST_RECIPIENT_EMAIL`

## Phase 2: Data Schema & Storage (locked 2026-08-31)

### Storage format: JSON files under `state/`
Decision: **JSON, not SQLite.** This is a single daily batch job with no concurrent writers and modest volume (realistically dozens to a few hundred records a year across all sources). SQLite's benefits — concurrent access, complex queries, indexing — aren't needed here, while JSON stays human-inspectable for debugging and has zero extra dependency. Revisit only if volume or query complexity grows materially.

`state/` is a **new top-level folder**, distinct from `.tmp/`: `.tmp/` holds disposable intermediates (regenerated freely), `state/` holds the persistent dedup/tracking record that must survive between runs and should NOT be wiped.

- `state/competitions.json` — dict keyed by `id` → competition record
- `state/training_camps.json` — dict keyed by `id` → training camp record
- `state/tips_library.json` — list of tip records (curated content, built in Phase 4)

### Dedup key strategy
No source provides a stable cross-run ID, so `id` is a deterministic hash: `sha1(normalize(name) + date_start + source_domain)`, truncated to 16 hex chars. `normalize()` = lowercase + collapse whitespace, to absorb minor text drift between scrapes of the same listing. Good enough to start; revisit once Phase 3 sees real extracted data and any near-duplicate collisions.

### Competition record schema
```
{
  "id": "sha1 hash, see above",
  "name": "string",
  "level": "state | national | international | open",
  "discipline": "string, e.g. '10m Air Rifle', '50m Rifle 3-Position'",
  "location": { "venue": "string", "city": "string", "state": "string|null", "country": "string" },
  "date_start": "YYYY-MM-DD",
  "date_end": "YYYY-MM-DD|null",
  "registration_deadline": "YYYY-MM-DD|null",
  "eligibility": { "age_category": "string|null", "gender_category": "string|null", "membership_required": "string|null", "notes": "string|null" },
  "entry_path": "federation-selection | open-entry | unclear",
  "organizing_body": "string",
  "source_name": "string, e.g. 'NRAI', 'Maharashtra Rifle Association', 'ISSF'",
  "source_url": "string, the specific page/circular used for extraction",
  "status": "confirmed | tentative | announced",
  "confidence": "high | medium | low",
  "first_seen_date": "YYYY-MM-DD, when this id was first scraped",
  "last_seen_date": "YYYY-MM-DD, most recent scrape that still found it",
  "reminders_sent": ["new_listing", "deadline_7d", "deadline_2d"]
}
```
`confidence` implements the doc's "no false negatives over false positives" rule — uncertain extractions still get emailed, just flagged `low`, rather than silently dropped. `reminders_sent` implements the dedup/reminder rule: the email composer (Phase 4) only sends a reminder type once per id, checked against today's date vs. `registration_deadline`.

### Training camp record schema
```
{
  "id": "same hashing scheme as competitions",
  "name": "string",
  "date_start": "YYYY-MM-DD",
  "date_end": "YYYY-MM-DD|null",
  "location": { "venue": "string", "city": "string", "state": "string|null", "country": "string" },
  "hosting_body": "string, e.g. 'NRAI', 'Asian Shooting Confederation'",
  "discipline_focus": "string, e.g. 'Rifle', 'All disciplines'",
  "coaches": ["string, optional — e.g. named foreign coaches"],
  "participation_criteria": "string|null — often invite-only/selection-based",
  "application_process": "string|null",
  "entry_path": "federation-selection | open-entry | unclear",
  "source_name": "string",
  "source_url": "string",
  "status": "confirmed | tentative | announced",
  "confidence": "high | medium | low",
  "first_seen_date": "YYYY-MM-DD",
  "last_seen_date": "YYYY-MM-DD",
  "notified": "boolean, default false"
}
```
No `reminders_sent` for camps (no deadline-countdown behavior — most don't have a hard registration deadline the way competitions do), but a `notified` boolean **is required** (added 2026-08-31 during Phase 4 build — the original schema draft omitted it, which would have meant the email composer had no way to avoid re-mentioning the same camp every single day). The composer sets it `true` after a camp is included in a successfully-sent email, exactly like `reminders_sent` gates competitions.

### Tips library record schema
```
{
  "id": "short slug, e.g. 'trigger-control-01'",
  "category": "technique | mental | equipment | interview-insight",
  "text": "2-4 sentences, the tip itself",
  "source": "string|null, e.g. 'ISSF coaching article' or 'Abhinav Bindra interview'",
  "last_used_date": "YYYY-MM-DD|null, updated by the email composer for rotation"
}
```
Curating the actual ~30-60 tips is Phase 4 work (per the project doc); this schema just fixes the shape so Phase 4 doesn't have to redesign it.

## Phase 3: Fetch + Extract (built and validated 2026-08-31)

### Fetch — `tools/fetch_sources.py` (deterministic tool)
Run `python tools/fetch_sources.py` (or `--source <key>` for one source, `--list` to see keys, `--yearly-sweep` to also run the weekly next-year-calendar sweep). It hits Firecrawl/SerpAPI per the verified sources above, follows PDF/circular links found on listing pages, and writes:
- Raw markdown/JSON per item to `.tmp/raw/`
- A manifest at `.tmp/fetch_manifest.json` (source, url, output file, status, timestamp) — this manifest is the handoff point to the extraction step.

**Bugs found and fixed while building this (see "Known pitfalls" above for full detail):** markdown links with a quoted title (`[text](url "title")`) weren't matched by the first regex; Firecrawl 429s under rapid sequential requests, fixed with ~6.5s pacing + retry/backoff.

### Extract — agent judgment, not a script
Per the WAT split (deterministic tools vs. agent reasoning), turning raw scraped text into records matching the schemas above is **not** a separate tool that calls out to another LLM — it's done directly by whichever agent runs this workflow, reading `.tmp/fetch_manifest.json` and the files it points to, then writing structured records. This was validated end-to-end on 2026-08-31: 8 competitions and 3 training camps were extracted from the real fetched data and written to `.tmp/extracted_competitions.json` / `.tmp/extracted_training_camps.json`, then merged into `state/competitions.json` / `state/training_camps.json` (first-run seed, done by hand since the Phase 4 merge/dedup tool doesn't exist yet).

**Extraction lessons learned:**
- Cross-checking NRAI's calendar against ISSF's calendar independently confirmed the same international dates (Asian Games, ISSF World Cups) — a useful consistency check when available.
- A fetched circular is not always the right document: some MRA "Circular" links turned out to be relay/squad-list schedules (shooter names + time slots) with no eligibility/deadline info, and others revealed their discipline (e.g. Shotgun-only) only inside the PDF body, not the link text/URL. The extraction step must actually read each document rather than trust the calendar page's link text.
- Where a circular's actual eligibility text wasn't available (e.g. MAFC 2026/2 — only relay PDFs were fetched, not the master circular), the record was still included per the "no false negatives" rule, with `confidence: "low"` and `entry_path: "unclear"` rather than being dropped.
- International fixtures are almost universally `entry_path: "federation-selection"` (Indian team selected via NRAI trials) — confirmed directly in the source text (e.g. "TEAM TO BE SELECTED AFTER TRIAL 4").

## Phase 4: Dedup + Tips + Email (built and validated 2026-08-31 — zero paid API calls)

### Dedup/merge — `tools/merge_records.py`
Pure local JSON read/write, no network calls. Ingests `.tmp/extracted_competitions.json` / `.tmp/extracted_training_camps.json` (the agent's extraction output) into `state/*.json`. New ids are inserted fresh; existing ids get all fields refreshed except `first_seen_date`, `reminders_sent` (competitions), and `notified` (camps) — those carry send-history and must survive a re-scrape untouched. Tested idempotently against the Phase 3 seed data: correctly reported "0 new, 8/3 updated" with `reminders_sent`/`notified` preserved.

**Schema gap found and fixed while building this:** the original training-camp schema had no way to track whether a camp had already been emailed once — every run would have re-included every camp forever. Added a `notified` boolean field (see schema above) as the camp equivalent of `reminders_sent`.

### Tips library — `state/tips_library.json`
21 tips hand-curated directly (no API calls — this is stable, well-established shooting-sports domain knowledge), spread across all four schema categories: technique (6), mental (6), equipment (5), interview-insight (4, framed as general public knowledge/commentary about Bindra/Elavenil rather than unverifiable direct quotes). Rotation picks the tip with the oldest/null `last_used_date`.

### Compose + send — `tools/send_daily_digest.py`
Selection rules: a competition is included if `"new_listing"` isn't yet in its `reminders_sent`, or if its `registration_deadline` is exactly 7 or 2 days out and that reminder type hasn't been sent; a camp is included if `notified` is false. **Defaults to a dry run** — prints the composed digest and writes it to `.tmp/digest_preview.txt`, but sends nothing and touches no state. Pass `--send` to actually email via Gmail SMTP (needs `GMAIL_SENDER_EMAIL` + `GMAIL_APP_PASSWORD` in `.env`, free within Gmail's normal sending limits) — only a successful send triggers the state write-back (`reminders_sent`/`notified`/tip `last_used_date`), so a failed send never falsely marks something as sent.

Validated end-to-end in dry-run mode on the real Phase 3 data: composed all 8 competitions + 3 camps + 1 tip correctly, and confirmed dry run leaves `state/` completely untouched.

**Real send confirmed working (2026-08-31):** the user set up a Gmail App Password (`GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` in `.env`), and `--send` successfully delivered the plain-text digest to chetanmuley01@gmail.com, with `state/` correctly updated (`reminders_sent`/`notified`/tip rotation all advanced).

### Visual branding — "Sightline" (added 2026-08-31)
The digest was upgraded from plain text to a styled HTML email. The user provided `assets/beacom_logo.png` and `assets/beacom_brand_guidelines.png` — the brand guide for **Beacom, an unrelated product** (a screen-free voice-calling device for kids, getbeacom.com). Per the user's explicit choice, this pipeline reuses only Beacom's **visual system** (palette + typography), not its name or logo:
- Palette: Night Plum `#1F1826` (background), Plum Panel `#29222F` (cards), Amber `#F3A63C` (competitions accent), Cousin Teal `#6FB6B4` (training camps accent), Cream `#F2ECE1` (headline text), Taupe `#AFA69A` (body/meta text)
- Type: Fraunces (serif headlines/wordmark), Karla (body), IBM Plex Mono (uppercase eyebrow labels/badges) — loaded via Google Fonts `<link>` with system-font fallbacks (Georgia/Helvetica/Consolas) since email clients have inconsistent web-font support
- This digest's own name/wordmark is **"Sightline"** (not Beacom) with the tagline "SCAN. TRACK. AIM." — no logo mark, text wordmark only
- Amber marks new competitions, teal marks new training camps — mirrors Beacom's own "one accent color per thing it represents" convention from the guide

`tools/send_daily_digest.py` now builds both a plain-text part and an HTML part (sent as `multipart/alternative` so non-HTML clients still get the text version) and writes `.tmp/digest_preview.html` for visual QA in a browser. Sending real HTML email needs table-based layout and inline CSS throughout (no `<style>` blocks, no flexbox/grid) for cross-client compatibility — Outlook desktop in particular ignores `border-radius` and modern CSS, so the design degrades gracefully rather than breaking.

**Safety net for visual testing — `--test-send`:** sends a real email via Gmail SMTP built from *all* current records (ignoring `reminders_sent`/`notified` filters) but **never writes to `state/`** — used to visually verify the template in actual Gmail without disturbing production dedup tracking. Safe to re-run as many times as needed while iterating on the design. Validated 2026-08-31: sent successfully, confirmed `state/` untouched afterward.

## Phase 5: Scheduling (built 2026-08-31)

**Measured recurring cost:** 24 Firecrawl calls + 1 SerpAPI call per daily run; +2 SerpAPI calls on the weekly next-year-calendar sweep. ~720 Firecrawl + ~38 SerpAPI calls/month. Check this against your plan limits before scheduling — not verifiable from inside a Claude Code session.

**Architecture decisions (user-approved):**
- **Trigger:** Windows Task Scheduler running local scripts — zero new services, zero new cost, keeps all state/secrets as local files. (Considered Trigger.dev: has a genuine free tier and Python support, but requires migrating `state/*.json` off local disk since its tasks run in ephemeral cloud containers with no persistent disk between runs, plus moving `.env` secrets into its vault, plus metered compute beyond its $5/month credit. Rejected as unnecessary complexity/risk for this use case — reconsider only if reliability without the PC being on becomes a real problem.)
- **Extraction:** deterministic (regex-based) parsers, not agent judgment — `tools/extract_deterministic.py`. Rejected the alternative (Task Scheduler invoking `claude -p` headlessly) because whether that draws from a Pro/Max subscription or needs separate metered billing could not be confirmed from inside this session. Deterministic parsing means the daily run's cost is 100% Firecrawl/SerpAPI, fully known — trading off some quality/adaptability (fragile if a source changes format) for total cost certainty.

### `tools/extract_deterministic.py`
Reliable, tested parsers for the structurally consistent sources:
- **NRAI PDF calendars** — clean markdown tables (`| S.NO. | DATES | PARTICULARS | VENUE | REMARKS |`)
- **ISSF calendar** — structurally consistent `[DATE\\\n\\\nNAME\\\n\\\n![](flag)LOCATION](url)` pattern in the Firecrawl markdown
- **MRA competitions listing** — structured `### Name` / `[Circular](url)` / `**Date:** ... **Location:** ...` cards

Best-effort regex enrichment for MRA's free-text circular PDFs (registration deadline only, via a "last date...entries...DATE" phrase match) — left blank rather than guessed wrong when no match is found.

**Not auto-extracted:** ASC homepage and SGFI search results are too unstructured (mixed news/cards, bare search snippets) to parse reliably without judgment. These get flagged into `.tmp/needs_manual_review.md` instead of risking fabricated structured data — an honest scope reduction, not an oversight.

**Real bugs found and fixed while building/testing this against Phase 3's already-fetched data (zero extra API cost to find these):**
1. **Routing bug that silently dropped all NRAI PDF data**: the fetch manifest labels followed links as `"nrai_calendar_page (linked circular)"`, not an exact match on the base source name — an exact-equality routing check missed every one of them. Caught by noticing 0 NRAI-table competitions in the output despite 4 successfully-fetched PDFs.
2. **Markdown-escaped brackets leaking into names** (`\[MAFC 2026/2\]`) — needed explicit unescaping.
3. **No past-event filtering** — the full-year NRAI calendar includes months already gone by; a record needs date_end (or date_start) `>= today` to be worth keeping.
4. **Cross-discipline merge bug**: naive name-token-overlap dedup merged "...Championship Rifle" with "...Championship Pistol" because 5 of 7 words were shared template boilerplate — silently dropped one of the two real, distinct events. Fixed by treating RIFLE/PISTOL/SHOTGUN as a hard discriminator: two names can only merge if they don't assign conflicting discipline tags.
5. **Cross-zone merge bug**, same root cause: "13th West Zone..." merged with "45th North Zone..." on template-word overlap. Fixed the same way, treating zone (WEST/NORTH/SOUTH/EAST/NORTH EAST ZONE) as a second hard discriminator.
6. **A literal typo in the source PDF** — "SEPTMEBER" instead of "SEPTEMBER" in the real NRAI calendar — broke exact month-name lookup, silently producing a null date. Fixed with a fuzzy fallback (`difflib.get_close_matches`) rather than trying to enumerate every possible typo.

These hard-discriminator and typo-tolerance fixes live in `tools/fuzzy_match.py` (shared with `merge_records.py`, see below) and `tools/date_utils.py`.

### `tools/merge_records.py` — hardened with fuzzy fallback matching
Switching extraction methods mid-project surfaced a real problem: the same real-world event got a different id from manual (Phase 3) vs. deterministic (Phase 5) extraction, because the id partly derives from name text and source URL, and both changed. Exact-id-only merging would have created 7+ duplicate competitions and re-sent already-delivered events as "new" — a real duplicate-email bug, not a hypothetical one.

Fixed by adding a fuzzy-match fallback: when an extracted record's id isn't found in `state/`, check it against existing state records using the same name-overlap + date-proximity + hard-discriminator logic as the cross-source dedup above. **Validated on the real migration (2026-08-31):** 7 of 8 existing competitions and 2 of 3 existing camps were correctly recognized as the same real events (their `reminders_sent`/`notified`/`first_seen_date` history preserved intact, not reset), while 16 genuinely new competitions and 7 genuinely new camps were added. The one unmatched old record (a 2027 placeholder sourced from ASC, which deterministic extraction doesn't cover) was correctly left untouched rather than dropped. This fallback is permanent, not a one-time migration hack — it also protects against ordinary drift (a source renaming an event, changing a PDF filename) going forward.

### `tools/run_daily_pipeline.py` — orchestrator for Task Scheduler
Chains `fetch_sources.py` → `extract_deterministic.py` → `merge_records.py` → `send_daily_digest.py --send`, aborting before the next step if any one fails (so a broken fetch never leads to sending an empty or garbage digest). Logs every run to `logs/pipeline.log` since no one watches an unattended run in real time. Has a `--skip-fetch` test mode (reuses cached `.tmp/raw/` data, zero API cost) for validating the wiring — **note this still calls `send_daily_digest.py --send` for real**, so only use it when you actually want to send whatever is currently pending in `state/`.

### Known remaining imperfection (accepted, documented rather than over-engineered)
A small number of near-duplicate records can still slip through cross-source dedup when two sources describe the same event with almost no shared vocabulary (e.g. NRAI's "69TH NATIONAL SHOOTING CHAMPIONSHIP COMPETITIONS" vs the same body's own "69TH NSCC RIFLE/PISTOL/SHOTGUN" in a different PDF — only "69TH" is shared). Per the project's "no false negatives over false positives" principle, an occasional harmless near-duplicate is preferable to further tuning that risks re-introducing a false-merge bug like #4/#5 above.

## Phase 5 activation (2026-08-31)
- **Pending digest sent:** the 16 new competitions + 7 new camps from the real migration merge were emailed; `state/` confirmed fully caught up (0 unsent competitions, 0 unnotified camps) immediately after.
- **Task Scheduler registered:** task `SightlineDailyPipeline`, daily trigger at 9:00 AM, runs `tools/run_daily_pipeline.py`, logs to `logs/pipeline.log`. Registered to run only when the user is logged on (no stored credential) — the PC needs to be on and signed in at 9 AM. First scheduled run: 2026-09-01 09:00.
- **Not yet done:** the weekly next-year-calendar sweep has no scheduled task — daily-only for now per the user's choice. Revisit once the daily task's reliability is confirmed over a few real runs.
