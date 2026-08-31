"""Orchestrates the full daily pipeline for unattended (Task Scheduler) runs:
fetch_sources.py -> extract_deterministic.py -> merge_records.py ->
send_daily_digest.py --send.

Costs real money each run: ~24 Firecrawl calls + 1 SerpAPI call (measured in
Phase 3/5 testing). This script does NOT run on its own — it must be
registered as a Windows Task Scheduler task, and that registration is a
separate, explicit step the user approves (see workflows/scan_rifle_competitions.md
cost-control checkpoint). Do not add this to Task Scheduler without that
approval already given.

Stops early (does not send an email) if fetching fails outright, so a broken
source doesn't lead to sending an empty or garbage digest silently.

Every run's output is appended to logs/pipeline.log, since no one is watching
an unattended run in real time.

Usage:
    python tools/run_daily_pipeline.py              # real run: fetch, extract, merge, send
    python tools/run_daily_pipeline.py --skip-fetch  # reuse existing .tmp/raw data — for
                                                      # testing the orchestration wiring
                                                      # without spending Firecrawl/SerpAPI
                                                      # credits. Never use this for a real
                                                      # scheduled run.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_PATH = os.path.join(LOG_DIR, "pipeline.log")


def run_step(name: str, args: list, log) -> bool:
    log.write(f"\n--- {name} ---\n")
    log.flush()
    result = subprocess.run(
        [sys.executable] + args,
        cwd=PROJECT_ROOT,
        capture_output=True, text=True,
    )
    log.write(result.stdout)
    if result.stderr:
        log.write("STDERR:\n" + result.stderr)
    log.flush()
    print(f"{name}: {'OK' if result.returncode == 0 else 'FAILED (exit ' + str(result.returncode) + ')'}")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-fetch", action="store_true",
                         help="Reuse existing .tmp/raw data instead of calling Firecrawl/SerpAPI. "
                              "For testing the pipeline wiring only — never use for a real scheduled run.")
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        log.write(f"\n{'=' * 60}\nPipeline run: {datetime.now().isoformat()}"
                   f"{' (SKIP-FETCH TEST MODE)' if args.skip_fetch else ''}\n{'=' * 60}\n")

        if not args.skip_fetch:
            if not run_step("fetch_sources", [os.path.join(TOOLS_DIR, "fetch_sources.py")], log):
                log.write("\nABORTED: fetch failed, not proceeding to extract/merge/send.\n")
                print("Fetch failed — aborting before extract/merge/send. See logs/pipeline.log for details.")
                return 1
        else:
            log.write("\n(skipped fetch — reusing existing .tmp/raw data)\n")
            print("Skipping fetch (test mode) — reusing existing .tmp/raw data.")

        if not run_step("extract_deterministic", [os.path.join(TOOLS_DIR, "extract_deterministic.py")], log):
            log.write("\nABORTED: extraction failed, not proceeding to merge/send.\n")
            print("Extraction failed — aborting before merge/send. See logs/pipeline.log for details.")
            return 1

        if not run_step("merge_records", [os.path.join(TOOLS_DIR, "merge_records.py")], log):
            log.write("\nABORTED: merge failed, not proceeding to send.\n")
            print("Merge failed — aborting before send. See logs/pipeline.log for details.")
            return 1

        send_ok = run_step("send_daily_digest", [os.path.join(TOOLS_DIR, "send_daily_digest.py"), "--send"], log)
        if not send_ok:
            log.write("\nWARNING: send failed. state/ was already updated by merge_records — check logs/pipeline.log.\n")
            print("Send failed — check logs/pipeline.log. (state/ was still updated by the merge step.)")
            return 1

        log.write("\nPipeline run completed successfully.\n")
        print("Pipeline completed successfully. See logs/pipeline.log for full detail.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
