# Project: Rifle Shooting Competition Daily Alerts

## Goal
Build an automated system that scans for rifle shooting competitions — state-level, national-level, and international-level (10m air rifle and other rifle events) — and sends a daily email digest so Rutuja can find and register for competitions to work toward a state, national, or international medal. The digest also tracks training camps (India and abroad, including foreign-coached camps) for awareness, and includes a rifle shooting tip/technique for the day.

## Why
Rutuja competes in rifle shooting (10m air rifle). We want to systematically track every open competition she's eligible for (club, district, state, national) instead of missing registrations because we didn't know they existed — and to stay aware of the international calendar (ISSF/Asian-level competitions and training camps) so she and her coach can plan toward national-team selection, even though most international events are entered by federation nomination rather than individual sign-up. We also build in daily practice tips so the email is useful even on days with no new competitions.

## Build Plan — Waterfall Phases
This project should be built in Claude Code as a strict sequence — each phase finishes and is confirmed working before the next starts. Don't let the agent jump ahead to Phase 4 before Phase 1–3 are solid; that's how these pipelines end up half-broken.

**Phase 1 — Requirements & Source Discovery** ✅ done (2026-08-31) — full detail in `workflows/scan_rifle_competitions.md`
- Lock down: recipient email, states to track, which web scraper API (if any) to use — chetanmuley01@gmail.com; Maharashtra + national + international; Firecrawl + SerpAPI
- Manually verify 3-5 real competition notices to understand the actual format/structure of the data (this defines what the extractor needs to parse) — NRAI, MRA, ISSF, ASC all verified live

**Phase 2 — Design** ✅ done (2026-08-31) — full schema and storage decision in `workflows/scan_rifle_competitions.md`
- Define the data schema (competition name, level, location, date, deadline, eligibility, link, source) — includes `entry_path` and `confidence` fields, plus a separate Training Camps schema
- Define the tips/tricks content schema and source — schema locked, actual curated content deferred to Phase 4 as planned
- Decide storage format (JSON file vs. SQLite) for dedup tracking — JSON, under new `state/` folder

**Phase 3 — Build: Fetch + Extract** ✅ done (2026-08-31) — full detail in `workflows/scan_rifle_competitions.md`
- Build the fetcher (web scraper API or direct scraping) for each confirmed source — `tools/fetch_sources.py`, tested against all 6 sources (25/25 items fetched successfully)
- Build the LLM-based extraction step that turns raw scraped text into structured competition records — done as agent-driven extraction (not a separate script, per the WAT tools-vs-judgment split); validated end-to-end with 8 real competitions + 3 real training camps now seeded in `state/`

**Phase 4 — Build: Dedup + Tips + Email** ✅ done (2026-08-31) — zero paid API calls, full detail in `workflows/scan_rifle_competitions.md`
- Build dedup logic against stored records — `tools/merge_records.py`, pure local JSON, tested idempotently
- Build/curate the daily tips & tricks content — 21 tips hand-curated in `state/tips_library.json`
- Build the email composer + sender — `tools/send_daily_digest.py`, defaults to a dry run (no send, no state change); real sending needs the user to add a free Gmail App Password to `.env` first

**Phase 5 — Schedule + Test** ✅ live (2026-08-31) — full detail in `workflows/scan_rifle_competitions.md`
- Trigger: Windows Task Scheduler, task `SightlineDailyPipeline`, daily at 9:00 AM (considered Trigger.dev, rejected — would require migrating state/secrets to the cloud for a use case that doesn't need it)
- Extraction: deterministic parsers (`tools/extract_deterministic.py`), not agent judgment — avoids any Claude-billing ambiguity in the unattended run
- Orchestrator `tools/run_daily_pipeline.py` registered and active — next run 2026-09-01 09:00. Real recurring cost: ~24 Firecrawl + 1 SerpAPI call/day. Logs to `logs/pipeline.log`.
- The one-time pending digest from the extraction-method migration (16 new competitions + 7 new camps) was sent 2026-08-31; `state/` is now fully caught up (0 unsent).
- Weekly next-year-calendar sweep is NOT yet scheduled (daily-only for now, per user's choice) — revisit once the daily task is confirmed stable.
- Wire up daily scheduling (cron or n8n)
- Run for 1-2 weeks, compare what's found vs. what's actually published, tune sources

**Phase 6 — Maintain**
- Periodically add new sources/states
- Rotate/expand the tips & tricks library so emails don't repeat too often

## Core Requirements

1. **Daily scan** — runs once a day (e.g., every morning) and checks for new/upcoming rifle shooting competitions and training camps, in India and internationally.
2. **Scope of events to track**:
   - 10m Air Rifle (and other rifle disciplines: 50m rifle, 3-position, etc.)
   - State-level competitions (Maharashtra to start, expandable to all states)
   - National-level competitions (NRAI-affiliated, state associations, School Games Federation, university meets, etc.)
   - **International-level competitions** (ISSF World Cups/Championships, Asian Shooting Confederation Championships/Games) — tracked for awareness even though most are entered by national-federation nomination, not individual sign-up
   - Open/eligible-for-anyone competitions (not restricted to existing federation members only, where possible)
   - **Training camps** (India-hosted elite/national camps with foreign coaches, and international camps such as Asian Shooting Confederation youth/coaching camps) — tracked as their own category, separate from competitions
3. **Email digest** — one daily email with:
   - **Competitions section**: name, level (state/national/international/open), location, date(s), registration deadline, eligibility criteria (age/gender/license/membership), **entry path** (`federation-selection` / `open-entry` / `unclear` — whether Rutuja can register directly or it requires national-team selection), link to official notification/registration page, organizing body
   - **Training camps section**: camp name, dates, location, hosting body, discipline/coaching focus, application process (if any), link
4. **Dedup logic** — don't re-email the same competition or camp every day; only send new listings, and maybe a reminder as the registration deadline approaches (e.g., 7 days and 2 days before).
5. **No false negatives over false positives** — better to include a maybe-relevant event than silently skip it. Flag uncertain matches instead of dropping them.

## Candidate Data Sources
*(to be verified/expanded during build — official sources are scattered and not centralized)*
- National Rifle Association of India (NRAI) — official notices/circulars, and the national elite training camp (foreign coaches)
- Maharashtra Rifle Association / relevant state rifle association website
- School Games Federation of India (if age-eligible)
- **International Shooting Sport Federation (ISSF)** — `issf-sports.org/calendar` — World Cups, World/Junior Championships (verified: static HTML calendar, no eligibility info on the list page itself, need individual event pages for that)
- **Asian Shooting Confederation (ASC)** — `asia-shooting.org` — Asian Championships/Games, and Asian-level training/coaching camps (verified: has both competition and camp listings, e.g. Asian Youth Training & Coaching Camp)
- Shooting Ballistics magazine / India shooting news sites
- State Olympic Association / Sports department circulars (Maharashtra Sports Dept)
- Google Alerts / News search for "rifle shooting competition India [state]"
- Instagram/Facebook pages of state rifle associations (many post there before official sites)

## Daily Tips & Tricks (for the email)
Each daily email should include one rifle shooting tip alongside the competition listings, so it's valuable even on no-news days.

**Content sources to pull from / curate:**
- Standard 10m air rifle technique fundamentals: stance, natural point of aim, breathing control, trigger control, follow-through
- Mental training / focus routines used in shooting sports (pre-shot routine, dealing with competition nerves)
- Equipment care and setup tips (rifle maintenance, sight settings, kit checklist for competition day)
- NRAI / ISSF coaching articles and Olympic shooter interviews (Abhinav Bindra, Elavenil Valarivan, etc. often share technique insights)
- A simple rotating library (e.g., 30-60 curated tips) so the same tip doesn't repeat too often — can start hand-curated, later auto-refreshed via search

**Format in email:** one short "Tip of the Day" block (2-4 sentences) placed above or below the competition list.

## Web Scraper API — Provision (budget approved)
You're open to paying for a web scraper API rather than relying only on free scraping, since competition notices are scattered and inconsistent. This should be evaluated in Phase 1 and can be swapped later if it's not finding enough.

**Candidates to evaluate in Claude Code:**
- **ScraperAPI** — general-purpose scraping, handles JS-rendering/proxies, pay-as-you-go
- **Bright Data** — enterprise-grade, more expensive, best if sources block simpler scrapers
- **Apify** — has pre-built "actors" for site scraping + can run scheduled jobs itself (could even replace the cron/n8n scheduler)
- **SerpAPI** — useful specifically for pulling Google Search/News results (e.g., "rifle shooting competition Maharashtra 2026") rather than scraping a specific site
- **Firecrawl** — good for turning arbitrary web pages into clean markdown/text for the LLM extraction step

**Decision needed in Phase 1:** which one (or combination) to sign up for and set the API key up as an environment variable in the project — do not hardcode it in the markdown or scripts.

## Proposed Architecture
- **Scraper/fetcher module**: pulls pages from the above sources (web scraping or RSS/API where available)
- **Extraction step**: use an LLM (Claude) to parse unstructured competition notices into structured fields (name, level, date, location, deadline, eligibility, link)
- **Storage**: JSON files under `state/` (`state/competitions.json`, `state/training_camps.json`, `state/tips_library.json`) — chosen over SQLite since this is a single daily batch job with modest volume; see `workflows/scan_rifle_competitions.md` for the full schema
- **Scheduler**: cron job (or n8n workflow, since GTM/n8n is already in the toolkit) to run daily
- **Email sender**: SMTP / Gmail API / a transactional email service (e.g., Resend, SendGrid) to send the daily digest

## Open Questions / Decisions Needed
- Which email address should receive the digest?
- Should this run as a script on a schedule (cron/n8n) or as a Claude Code scheduled task?
- Do we want a simple text/HTML email, or a nicer formatted digest (table view)?
- Should reminders for approaching deadlines be a separate email or bundled into the daily digest?
- Which states beyond Maharashtra should be tracked first?

## Next Steps (for build in Claude Code)
Follow the Waterfall Phases above in order:
1. Lock down recipient email, target states, and pick a web scraper API — confirm data sources are actually scrapeable/reliable.
2. Design the schema for competitions and for tips content.
3. Build the fetcher + LLM extraction pipeline as a script.
4. Build dedup storage, curate/build the tips library, and build email sending.
5. Set up daily scheduling (cron or n8n) and test for 1-2 weeks.
6. Tune sources and expand tips library based on what's actually being found vs missed.
