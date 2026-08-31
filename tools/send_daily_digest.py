"""Compose and (optionally) send the daily rifle-competition digest email.
Phase 4: Dedup + Tips + Email. Pure local logic plus, only when --send is
passed, one free Gmail SMTP call. No paid APIs of any kind.

Selection rules (matches workflows/scan_rifle_competitions.md):
  - Competition: include if "new_listing" not yet in reminders_sent, OR if
    registration_deadline is exactly 7 or 2 days from today and that
    reminder type hasn't been sent yet.
  - Training camp: include if `notified` is false.
  - Tip: pick the one with the oldest/null last_used_date (simple rotation).

By default this is a DRY RUN: it prints the composed email and writes it to
.tmp/digest_preview.txt, but does not send anything and does not modify
state/. Pass --send to actually email it via Gmail SMTP (requires
GMAIL_SENDER_EMAIL and GMAIL_APP_PASSWORD in .env) — only on success does it
write back reminders_sent/notified/last_used_date to state/.

Usage:
    python tools/send_daily_digest.py            # dry run, no email sent
    python tools/send_daily_digest.py --send      # actually sends via Gmail SMTP
"""
import argparse
import html
import json
import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(PROJECT_ROOT, "state")
TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")

TODAY = date.today()
RECIPIENT = os.environ.get("DIGEST_RECIPIENT_EMAIL", "")
GMAIL_SENDER = os.environ.get("GMAIL_SENDER_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# "Sightline" visual style — palette/type approach borrowed from the Beacom
# brand guide's system (Night Plum/Amber/Teal, Fraunces + Karla + IBM Plex
# Mono) per the user's explicit "style only, not the Beacom name/logo" call.
NIGHT_PLUM = "#1F1826"
PLUM_PANEL = "#29222F"
AMBER = "#F3A63C"
TEAL = "#6FB6B4"
CREAM = "#F2ECE1"
TAUPE = "#AFA69A"

FONT_DISPLAY = "'Fraunces', Georgia, 'Times New Roman', serif"
FONT_BODY = "'Karla', Helvetica, Arial, sans-serif"
FONT_MONO = "'IBM Plex Mono', 'Courier New', monospace"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def days_until(date_str):
    if not date_str:
        return None
    return (date.fromisoformat(date_str) - TODAY).days


def select_competitions(competitions: dict):
    """Returns list of (record, reminder_type) to include this run."""
    selected = []
    for rid, rec in competitions.items():
        sent = set(rec.get("reminders_sent", []))
        if "new_listing" not in sent:
            selected.append((rid, rec, "new_listing"))
            continue
        d = days_until(rec.get("registration_deadline"))
        if d == 7 and "deadline_7d" not in sent:
            selected.append((rid, rec, "deadline_7d"))
        elif d == 2 and "deadline_2d" not in sent:
            selected.append((rid, rec, "deadline_2d"))
    return selected


def select_camps(camps: dict):
    return [(rid, rec) for rid, rec in camps.items() if not rec.get("notified", False)]


def select_tip(tips: list):
    if not tips:
        return None
    def sort_key(t):
        return t["last_used_date"] or "0000-00-00"
    return sorted(tips, key=sort_key)[0]


def format_competition(rec, reminder_type):
    label = {"new_listing": "NEW", "deadline_7d": "DEADLINE IN 7 DAYS", "deadline_2d": "DEADLINE IN 2 DAYS"}[reminder_type]
    loc = rec["location"]
    location_str = ", ".join(filter(None, [loc.get("venue"), loc.get("city"), loc.get("state"), loc.get("country")]))
    lines = [
        f"[{label}] {rec['name']}",
        f"  Level: {rec['level']} | Discipline: {rec['discipline']} | Status: {rec['status']} (confidence: {rec['confidence']})",
        f"  Dates: {rec['date_start']} to {rec['date_end'] or '?'}",
        f"  Location: {location_str or 'not specified'}",
        f"  Registration deadline: {rec['registration_deadline'] or 'not specified'}",
        f"  Entry path: {rec['entry_path']}",
        f"  Organizing body: {rec['organizing_body']}",
        f"  Source: {rec['source_name']} ({rec['source_url']})",
    ]
    elig = rec.get("eligibility") or {}
    elig_bits = [v for v in [elig.get("age_category"), elig.get("gender_category"), elig.get("membership_required")] if v]
    if elig_bits:
        lines.append(f"  Eligibility: {'; '.join(elig_bits)}")
    if elig.get("notes"):
        lines.append(f"  Note: {elig['notes']}")
    return "\n".join(lines)


def format_camp(rec):
    loc = rec["location"]
    location_str = ", ".join(filter(None, [loc.get("venue"), loc.get("city"), loc.get("state"), loc.get("country")]))
    lines = [
        f"[NEW] {rec['name']}",
        f"  Dates: {rec['date_start']} to {rec['date_end'] or '?'}",
        f"  Location: {location_str or 'not specified'}",
        f"  Hosting body: {rec['hosting_body']} | Focus: {rec['discipline_focus']}",
        f"  Entry path: {rec['entry_path']}",
        f"  Source: {rec['source_name']} ({rec['source_url']})",
    ]
    if rec.get("participation_criteria"):
        lines.append(f"  Participation: {rec['participation_criteria']}")
    return "\n".join(lines)


def compose(competitions_selected, camps_selected, tip):
    parts = [f"RIFLE SHOOTING DIGEST — {TODAY.isoformat()}", "=" * 50, ""]

    parts.append(f"COMPETITIONS ({len(competitions_selected)})")
    parts.append("-" * 30)
    if competitions_selected:
        for _, rec, reminder_type in competitions_selected:
            parts.append(format_competition(rec, reminder_type))
            parts.append("")
    else:
        parts.append("No new competitions or deadline reminders today.")
        parts.append("")

    parts.append(f"TRAINING CAMPS ({len(camps_selected)})")
    parts.append("-" * 30)
    if camps_selected:
        for _, rec in camps_selected:
            parts.append(format_camp(rec))
            parts.append("")
    else:
        parts.append("No new training camps today.")
        parts.append("")

    parts.append("TIP OF THE DAY")
    parts.append("-" * 30)
    if tip:
        parts.append(tip["text"])
        if tip.get("source"):
            parts.append(f"(Source: {tip['source']})")
    else:
        parts.append("No tips in the library yet.")

    return "\n".join(parts)


def _esc(s):
    return html.escape(str(s)) if s is not None else ""


def _badge_html(text, color):
    return (
        f'<span style="display:inline-block;font-family:{FONT_MONO};font-size:11px;'
        f'letter-spacing:0.06em;text-transform:uppercase;color:{NIGHT_PLUM};'
        f'background-color:{color};padding:3px 9px;border-radius:3px;font-weight:700;">'
        f'{_esc(text)}</span>'
    )


def _competition_card_html(rec, reminder_type):
    label = {"new_listing": "New", "deadline_7d": "Deadline in 7 days", "deadline_2d": "Deadline in 2 days"}[reminder_type]
    badge_color = AMBER if reminder_type == "new_listing" else TEAL
    loc = rec["location"]
    location_str = ", ".join(filter(None, [loc.get("venue"), loc.get("city"), loc.get("state"), loc.get("country")])) or "Not specified"
    elig = rec.get("eligibility") or {}
    elig_bits = [v for v in [elig.get("age_category"), elig.get("gender_category"), elig.get("membership_required")] if v]

    rows = [
        ("Dates", f"{rec['date_start']} to {rec['date_end'] or '?'}"),
        ("Location", location_str),
        ("Registration deadline", rec["registration_deadline"] or "Not specified"),
        ("Entry path", rec["entry_path"].replace("-", " ").title()),
        ("Organizing body", rec["organizing_body"]),
    ]
    if elig_bits:
        rows.append(("Eligibility", "; ".join(elig_bits)))
    if elig.get("notes"):
        rows.append(("Note", elig["notes"]))

    row_html = "".join(
        f'<tr><td style="font-family:{FONT_MONO};font-size:11px;color:{TAUPE};text-transform:uppercase;'
        f'letter-spacing:0.04em;padding:3px 10px 3px 0;vertical-align:top;white-space:nowrap;">{_esc(k)}</td>'
        f'<td style="font-family:{FONT_BODY};font-size:13px;color:{CREAM};padding:3px 0;vertical-align:top;">{_esc(v)}</td></tr>'
        for k, v in rows
    )

    return f'''
    <tr><td style="padding:0 0 16px 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{PLUM_PANEL};border-radius:8px;">
        <tr><td style="padding:18px 20px;">
          <div style="margin-bottom:8px;">{_badge_html(label, badge_color)}
            <span style="display:inline-block;font-family:{FONT_MONO};font-size:11px;color:{TAUPE};text-transform:uppercase;letter-spacing:0.04em;margin-left:8px;">{_esc(rec['level'])} &middot; {_esc(rec['discipline'])}</span>
          </div>
          <div style="font-family:{FONT_DISPLAY};font-size:19px;color:{CREAM};line-height:1.3;margin-bottom:10px;">{_esc(rec['name'])}</div>
          <table role="presentation" cellpadding="0" cellspacing="0">{row_html}</table>
          <div style="margin-top:10px;">
            <a href="{_esc(rec['source_url'])}" style="font-family:{FONT_MONO};font-size:11px;color:{TEAL};text-decoration:none;">Source: {_esc(rec['source_name'])} &rarr;</a>
          </div>
        </td></tr>
      </table>
    </td></tr>'''


def _camp_card_html(rec):
    loc = rec["location"]
    location_str = ", ".join(filter(None, [loc.get("venue"), loc.get("city"), loc.get("state"), loc.get("country")])) or "Not specified"
    rows = [
        ("Dates", f"{rec['date_start']} to {rec['date_end'] or '?'}"),
        ("Location", location_str),
        ("Hosting body", rec["hosting_body"]),
        ("Focus", rec["discipline_focus"]),
        ("Entry path", rec["entry_path"].replace("-", " ").title()),
    ]
    if rec.get("participation_criteria"):
        rows.append(("Participation", rec["participation_criteria"]))

    row_html = "".join(
        f'<tr><td style="font-family:{FONT_MONO};font-size:11px;color:{TAUPE};text-transform:uppercase;'
        f'letter-spacing:0.04em;padding:3px 10px 3px 0;vertical-align:top;white-space:nowrap;">{_esc(k)}</td>'
        f'<td style="font-family:{FONT_BODY};font-size:13px;color:{CREAM};padding:3px 0;vertical-align:top;">{_esc(v)}</td></tr>'
        for k, v in rows
    )

    return f'''
    <tr><td style="padding:0 0 16px 0;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{PLUM_PANEL};border-radius:8px;">
        <tr><td style="padding:18px 20px;">
          <div style="margin-bottom:8px;">{_badge_html("New", TEAL)}</div>
          <div style="font-family:{FONT_DISPLAY};font-size:19px;color:{CREAM};line-height:1.3;margin-bottom:10px;">{_esc(rec['name'])}</div>
          <table role="presentation" cellpadding="0" cellspacing="0">{row_html}</table>
          <div style="margin-top:10px;">
            <a href="{_esc(rec['source_url'])}" style="font-family:{FONT_MONO};font-size:11px;color:{TEAL};text-decoration:none;">Source: {_esc(rec['source_name'])} &rarr;</a>
          </div>
        </td></tr>
      </table>
    </td></tr>'''


def _section_header_html(eyebrow, count, accent):
    return f'''
    <tr><td style="padding:28px 0 12px 0;">
      <span style="font-family:{FONT_MONO};font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:{accent};">{_esc(eyebrow)} &middot; {count}</span>
    </td></tr>'''


def compose_html(competitions_selected, camps_selected, tip):
    comp_section = _section_header_html("Competitions", len(competitions_selected), AMBER)
    if competitions_selected:
        comp_section += "".join(_competition_card_html(rec, rt) for _, rec, rt in competitions_selected)
    else:
        comp_section += f'<tr><td style="font-family:{FONT_BODY};font-size:13px;color:{TAUPE};padding-bottom:16px;">No new competitions or deadline reminders today.</td></tr>'

    camp_section = _section_header_html("Training Camps", len(camps_selected), TEAL)
    if camps_selected:
        camp_section += "".join(_camp_card_html(rec) for _, rec in camps_selected)
    else:
        camp_section += f'<tr><td style="font-family:{FONT_BODY};font-size:13px;color:{TAUPE};padding-bottom:16px;">No new training camps today.</td></tr>'

    tip_html = ""
    if tip:
        source_line = f'<div style="font-family:{FONT_MONO};font-size:11px;color:{TAUPE};margin-top:8px;">Source: {_esc(tip["source"])}</div>' if tip.get("source") else ""
        tip_html = f'''
        <tr><td style="padding:28px 0 8px 0;">
          <span style="font-family:{FONT_MONO};font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:{AMBER};">Tip of the Day</span>
        </td></tr>
        <tr><td style="padding:0 0 8px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{PLUM_PANEL};border-radius:8px;border-left:3px solid {AMBER};">
            <tr><td style="padding:18px 20px;">
              <div style="font-family:{FONT_BODY};font-size:14px;line-height:1.55;color:{CREAM};">{_esc(tip['text'])}</div>
              {source_line}
            </td></tr>
          </table>
        </td></tr>'''

    return f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sightline — {_esc(TODAY.isoformat())}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,600;1,600&family=Karla:wght@400;700&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background-color:{NIGHT_PLUM};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{NIGHT_PLUM};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <tr><td style="padding-bottom:4px;">
    <span style="font-family:{FONT_MONO};font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:{AMBER};">Rifle Competition Digest &middot; {_esc(TODAY.isoformat())}</span>
  </td></tr>
  <tr><td style="padding-bottom:4px;">
    <span style="font-family:{FONT_DISPLAY};font-size:34px;color:{CREAM};">Sightline</span>
  </td></tr>
  <tr><td style="padding-bottom:20px;">
    <span style="font-family:{FONT_MONO};font-size:12px;letter-spacing:0.1em;color:{TEAL};">SCAN. TRACK. AIM.</span>
  </td></tr>
  <tr><td style="border-top:1px solid {PLUM_PANEL};padding-top:4px;"></td></tr>

  {comp_section}
  {camp_section}
  {tip_html}

  <tr><td style="padding:32px 0 4px 0;border-top:1px solid {PLUM_PANEL};">
    <span style="font-family:{FONT_MONO};font-size:10px;color:{TAUPE};">Sightline &middot; built for Rutuja's 2026 competition season &middot; not affiliated with NRAI, MRA, ISSF, or the Asian Shooting Confederation</span>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''


def send_via_gmail(subject: str, text_body: str, html_body: str):
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_SENDER_EMAIL and/or GMAIL_APP_PASSWORD missing from .env — cannot send.")
    if not RECIPIENT:
        raise RuntimeError("DIGEST_RECIPIENT_EMAIL missing from .env — cannot send.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_SENDER
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, [RECIPIENT], msg.as_string())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Actually send via Gmail SMTP (default: dry run only)")
    parser.add_argument("--test-send", action="store_true",
                         help="Send a real email via Gmail SMTP using ALL current records (ignoring "
                              "reminders_sent/notified), for visual testing only. Never writes to state/ "
                              "and never marks anything as sent — safe to run repeatedly.")
    args = parser.parse_args()

    comp_path = os.path.join(STATE_DIR, "competitions.json")
    camp_path = os.path.join(STATE_DIR, "training_camps.json")
    tips_path = os.path.join(STATE_DIR, "tips_library.json")

    competitions = load_json(comp_path, {})
    camps = load_json(camp_path, {})
    tips = load_json(tips_path, [])

    if args.test_send:
        comp_selected = [(rid, rec, "new_listing") for rid, rec in competitions.items()]
        camp_selected = [(rid, rec) for rid, rec in camps.items()]
    else:
        comp_selected = select_competitions(competitions)
        camp_selected = select_camps(camps)
    tip = select_tip(tips)

    body = compose(comp_selected, camp_selected, tip)
    html_body = compose_html(comp_selected, camp_selected, tip)
    subject_prefix = "[TEST] " if args.test_send else ""
    subject = f"{subject_prefix}Sightline — {TODAY.isoformat()}"

    os.makedirs(TMP_DIR, exist_ok=True)
    preview_path = os.path.join(TMP_DIR, "digest_preview.txt")
    html_preview_path = os.path.join(TMP_DIR, "digest_preview.html")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(body)
    with open(html_preview_path, "w", encoding="utf-8") as f:
        f.write(html_body)

    print(body)
    print(f"\n(Text preview: {os.path.relpath(preview_path, PROJECT_ROOT)})")
    print(f"(HTML preview: {os.path.relpath(html_preview_path, PROJECT_ROOT)} — open in a browser to see the styled version)")

    if not args.send and not args.test_send:
        print("\nDRY RUN — nothing sent, state/ not modified. Pass --send to actually email this, or --test-send for a visual test.")
        return 0

    send_via_gmail(subject, body, html_body)
    print(f"\nSent to {RECIPIENT}.")

    if args.test_send:
        print("TEST SEND — state/ not modified (reminders_sent/notified/tip rotation untouched).")
        return 0

    for rid, _, reminder_type in comp_selected:
        competitions[rid].setdefault("reminders_sent", []).append(reminder_type)
    for rid, _ in camp_selected:
        camps[rid]["notified"] = True
    if tip:
        for t in tips:
            if t["id"] == tip["id"]:
                t["last_used_date"] = TODAY.isoformat()

    save_json(comp_path, competitions)
    save_json(camp_path, camps)
    save_json(tips_path, tips)
    print("state/ updated (reminders_sent / notified / tip rotation).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
