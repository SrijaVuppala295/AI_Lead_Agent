"""
menu.py — Main Entry Point
============================
Run: python main.py

3 options:
  1 → Lead Gen Agent     — signals → classify → contacts → Sheets/Excel
  2 → AI Email Generator — discover emails → generate AI sequences
  3 → Discord Bot        — send emails, track replies, campaign management
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys


BANNER = """
╔══════════════════════════════════════════════════════════╗
║          STRIKIN LEAD GEN AGENT  v2.0                    ║
║          PropTech Outreach Automation                    ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  1 → Run Lead Gen Agent                                  ║
║      Signals → AI Classify → Find Contacts               ║
║      → Google Sheets → Excel backup                      ║
║                                                          ║
║  2 → AI Email Generator                                  ║
║      Auto-discover emails → Generate personalized        ║
║      original + 3 followups per lead via AI              ║
║                                                          ║
║  3 → Launch Discord Campaign Bot                         ║
║      Send emails with /send command (original/followup)  ║
║      Check replies, view stats, manage campaigns         ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""


# ═══════════════════════════════════════════════════════════════════════════
# OPTION 1 — Lead Gen Agent
# ═══════════════════════════════════════════════════════════════════════════

def run_agent():
    from utils.database import (
        init_db, update_last_run_timestamp,
        mark_as_processed, get_lead_count
    )
    from agents.signal_monitor    import collect_all_signals
    from agents.intent_classifier import classify_all_signals
    from agents.contact_finder    import find_all_contacts
    from agents.discord_alerts    import send_hot_lead_alert, send_run_summary
    from agents.sheets_writer     import push_to_sheets
    from agents.excel_writer      import build_leads_xlsx

    init_db()
    signals = collect_all_signals()

    if not signals:
        print("\n  ℹ️  No new signals — pushing existing leads to Sheets")
        push_to_sheets()
        build_leads_xlsx()
        update_last_run_timestamp()
        return

    results = classify_all_signals(signals)
    find_all_contacts()

    hot_leads = results.get("hot_leads", [])
    if hot_leads:
        print(f"\n📣 Sending Discord alerts for {len(hot_leads)} hot leads...")
        for lead in hot_leads:
            success = send_hot_lead_alert(lead)
            if success:
                print(f"  ✅ Alert sent — {lead.get('company_name')}")

    for signal in signals:
        mark_as_processed(signal["url"], signal["source"])

    update_last_run_timestamp()

    print("\n📊 Exporting leads...")
    print("  → Pushing to Google Sheets...")
    if push_to_sheets():
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        print(f"  ✅ Google Sheets updated")
        print(f"  🔗 https://docs.google.com/spreadsheets/d/{sheet_id}")

    path = build_leads_xlsx()
    if path:
        print(f"  ✅ Excel saved → output/leads.xlsx")

    send_run_summary(results["stats"])

    stats = results["stats"]
    print(f"\n{'='*55}")
    print(f"✅ AGENT RUN COMPLETE")
    print(f"   Signals collected:  {stats['total_signals']}")
    print(f"   Leads found:        {stats['total_leads']}")
    print(f"   Hot leads (7+):     {stats['hot_leads']}")
    print(f"   Total leads in DB:  {get_lead_count()}")
    print(f"{'='*55}\n")


# ═══════════════════════════════════════════════════════════════════════════
# OPTION 2 — Email Submenu
# ═══════════════════════════════════════════════════════════════════════════

EMAIL_SUBMENU = """
  ┌─────────────────────────────────────────────────────┐
  │  ✉️   EMAIL PIPELINE — Choose a step                 │
  ├─────────────────────────────────────────────────────┤
  │                                                     │
  │  2a → Discover Emails                               │
  │       Search online + scan website + pattern gen    │
  │       Run this first before generating emails       │
  │                                                     │
  │  2b → Generate Original Emails                      │
  │       AI writes personalized cold email per lead    │
  │       Uses signal/funding/launch context            │
  │                                                     │
  │  2c → Generate Followup 1  (send on day 3)          │
  │       Value-add insight, references original        │
  │                                                     │
  │  2d → Generate Followup 2  (send on day 7)          │
  │       Soft check-in, different angle                │
  │                                                     │
  │  2e → Generate Followup 3  (send on day 14)         │
  │       Final breakup email, keeps door open          │
  │                                                     │
  │  2f → Generate All  (2b + 2c + 2d + 2e at once)    │
  │                                                     │
  │   0 → Back to main menu                             │
  │                                                     │
  └─────────────────────────────────────────────────────┘
"""


def _show_email_status():
    """Prints a quick status line before the submenu."""
    from utils.database import get_all_leads, get_campaign_stats
    leads  = get_all_leads()
    stats  = get_campaign_stats()
    with_email = sum(1 for l in leads if len(l) > 13 and l[13] and l[13] not in ["", "Not found", "TBD"])
    print(f"\n  📊 Quick status: "
          f"{len(leads)} leads | "
          f"{with_email} with email | "
          f"🤖 {stats['generated']} generated | "
          f"📤 {stats['sent']} sent | "
          f"💬 {stats['replied']} replied")


def run_option_2():
    from agents.sheets_writer import push_to_sheets
    from agents.excel_writer  import build_leads_xlsx   # FIX: was missing

    while True:
        _show_email_status()
        print(EMAIL_SUBMENU)

        try:
            sub = input("  Choose step (2a/2b/2c/2d/2e/2f/0): ").strip().lower()
        except KeyboardInterrupt:
            print("\n  Back to main menu.")
            return

        if sub == "0":
            print("\n  ↩️  Back to main menu.\n")
            return

        elif sub == "2a":
            _run_email_discovery()
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel with email column data

        elif sub == "2b":
            _run_generate_original()
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel with Sheet 3 emails

        elif sub == "2c":
            _run_generate_followup(1)
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel

        elif sub == "2d":
            _run_generate_followup(2)
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel

        elif sub == "2e":
            _run_generate_followup(3)
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel

        elif sub == "2f":
            _run_generate_all()
            push_to_sheets()
            build_leads_xlsx()   # FIX: rebuild Excel

        else:
            print(f"\n  ❌ Invalid choice '{sub}'. Use 2a / 2b / 2c / 2d / 2e / 2f / 0")
            continue

        # After each step — ask if they want to do another step
        try:
            again = input("\n  ↩️  Return to Email menu? (y/n): ").strip().lower()
            if again != "y":
                print("\n  Back to main menu.\n")
                return
        except KeyboardInterrupt:
            return


# ─────────────────────────────────────────────────────────────────────────
# Sub-step implementations
# ─────────────────────────────────────────────────────────────────────────

def _run_email_discovery():
    from agents.email_discovery import discover_all_emails
    from utils.database import get_leads_with_email

    print("\n" + "="*55)
    print("📧 STEP 2a — EMAIL DISCOVERY")
    print("="*55)
    print("  Search online → Scan website → Pattern generation")
    print("  Skips leads that already have emails")
    print("="*55)

    discover_all_emails()

    found = get_leads_with_email()
    print(f"\n  ✅ {len(found)} leads now have email addresses")
    if found:
        print(f"  → Run 2b to generate original emails")


def _run_generate_original():
    from agents.email_generator import (
        generate_original, save_email,
        SENDER_NAME, SENDER_COMPANY
    )
    from utils.database import get_leads_with_email, get_emails_for_lead
    from utils.rate_limiter import wait
    import time

    print("\n" + "="*55)
    print("🤖 STEP 2b — GENERATE ORIGINAL EMAILS")
    print("="*55)
    print("  AI writes personalized cold email per lead")
    print("  Skips leads that already have original email")
    print("="*55)

    leads = get_leads_with_email()
    if not leads:
        print("\n  ⚠️  No leads with email addresses. Run 2a first.")
        return

    generated = 0
    skipped   = 0
    failed    = 0

    for lead in leads:
        (lead_id, company_name, contact_name, contact_title,
         contact_email, urgency_score, company_website,
         signal_title, why_relevant) = lead

        # Skip if original already exists
        existing = get_emails_for_lead(lead_id)
        if any(e[7] == "original" for e in existing):
            print(f"\n  ⏭️  {company_name} — original already generated")
            skipped += 1
            continue

        print(f"\n  ✉️  {company_name} → {contact_name} <{contact_email}>")

        first_name = contact_name.split()[0] if contact_name not in ["Not found", "TBD"] else "there"
        result = generate_original(
            first_name, contact_title, company_name,
            company_website, signal_title, why_relevant
        )

        if result:
            from utils.database import save_email as db_save_email
            db_save_email(
                lead_id, company_name, contact_name, contact_email,
                result["subject"], result["body"], "original"
            )
            print(f"     ✅ Subject: {result['subject']}")
            preview = result["body"][:120].replace("\n", " ")
            print(f"     👁  {preview}...")
            generated += 1
        else:
            print(f"     ❌ Failed to generate")
            failed += 1

        wait("between_leads")

    print(f"\n{'─'*55}")
    print(f"  Generated: {generated} | Skipped: {skipped} | Failed: {failed}")
    print(f"  → Run 2c to generate Followup 1")
    print(f"{'─'*55}")


def _run_generate_followup(num: int):
    from agents.email_generator import generate_followup
    from utils.database import (
        get_leads_with_email, get_emails_for_lead, save_email as db_save_email
    )
    from utils.rate_limiter import wait

    fu_key   = f"followup_{num}"
    day_map  = {1: 3, 2: 7, 3: 14}
    days     = day_map[num]
    next_map = {1: "2d (Followup 2)", 2: "2e (Followup 3)", 3: "Option 3 — Discord Bot to send"}

    print("\n" + "="*55)
    print(f"🤖 STEP 2{'cde'[num-1]} — GENERATE FOLLOWUP {num}  (day {days})")
    print("="*55)
    print(f"  Generates followup #{num} for all leads that have original email")
    print(f"  All followups connect to original thread via References header")
    print("="*55)

    leads = get_leads_with_email()
    if not leads:
        print("\n  ⚠️  No leads with email addresses. Run 2a first.")
        return

    generated = 0
    skipped   = 0
    failed    = 0
    no_orig   = 0

    for lead in leads:
        (lead_id, company_name, contact_name, contact_title,
         contact_email, urgency_score, *_) = lead

        existing = get_emails_for_lead(lead_id)

        # Must have original before followup
        orig = [e for e in existing if e[7] == "original"]
        if not orig:
            print(f"\n  ⏭️  {company_name} — no original email yet, skipping")
            no_orig += 1
            continue

        # Skip if this followup already exists
        if any(e[7] == fu_key for e in existing):
            print(f"\n  ⏭️  {company_name} — {fu_key} already generated")
            skipped += 1
            continue

        original_subject = orig[0][5]  # subject column
        thread_id        = str(orig[0][0])  # email id for threading

        print(f"\n  ✉️  {company_name} → {contact_name} (followup {num})")

        first_name = contact_name.split()[0] if contact_name not in ["Not found","TBD"] else "there"
        result = generate_followup(first_name, company_name, original_subject, num, days)

        if result:
            db_save_email(
                lead_id, company_name, contact_name, contact_email,
                result["subject"], result["body"], fu_key,
                thread_id=thread_id
            )
            print(f"     ✅ Subject: {result['subject']}")
            generated += 1
        else:
            print(f"     ❌ Failed to generate")
            failed += 1

        wait("between_leads")

    print(f"\n{'─'*55}")
    print(f"  Generated: {generated} | Skipped: {skipped} | "
          f"No original: {no_orig} | Failed: {failed}")
    print(f"  → Next: {next_map[num]}")
    print(f"{'─'*55}")


def _run_generate_all():
    """Runs 2b + 2c + 2d + 2e in sequence."""
    print("\n" + "="*55)
    print("🤖 STEP 2f — GENERATE ALL EMAILS")
    print("="*55)
    print("  Running: Original → Followup 1 → Followup 2 → Followup 3")
    print("="*55)

    _run_generate_original()
    _run_generate_followup(1)
    _run_generate_followup(2)
    _run_generate_followup(3)

    print(f"\n{'='*55}")
    print(f"✅ ALL EMAILS GENERATED")
    print(f"   → Launch Option 3 (Discord Bot) to send them")
    print(f"{'='*55}")


# ═══════════════════════════════════════════════════════════════════════════
# OPTION 3 — Discord Bot
# ═══════════════════════════════════════════════════════════════════════════

def run_option_3():
    from agents.discord_bot import run_discord_bot
    run_discord_bot()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print(BANNER)

    try:
        choice = input("  Choose option (1/2/3): ").strip()
    except KeyboardInterrupt:
        print("\n  Exiting.")
        sys.exit(0)

    print()

    if choice == "1":
        run_agent()
    elif choice == "2":
        run_option_2()
    elif choice == "3":
        run_option_3()
    else:
        print(f"  ❌ Invalid option '{choice}'. Choose 1, 2, or 3.")
        main()


if __name__ == "__main__":
    main()