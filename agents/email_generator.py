"""
email_generator.py — AI Email Generator
=========================================
Sign-off: "Best Regards,\n{SENDER_NAME}" only — no title/email/phone/website
JSON sanitizer fixes "Invalid control character" crash
Retry x3 on any failure
"""

import json
import time
from utils.rate_limiter import wait
from utils.ai_router import call_ai
from utils.database import (
    get_leads_needing_email_gen,
    save_email,
    get_leads_with_email,
)

SENDER_NAME = "Strikin Team"
SENDER_COMPANY = "Strikin"


def _sanitize_json(text: str) -> str:
    """Replaces literal control chars inside JSON string values."""
    text = text.replace("```json", "").replace("```", "").strip()
    result        = []
    inside_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"' and (i == 0 or text[i-1] != '\\'):
            inside_string = not inside_string
            result.append(c)
        elif inside_string:
            if   c == '\n': result.append('\\n')
            elif c == '\r': result.append('\\r')
            elif c == '\t': result.append('\\t')
            else:           result.append(c)
        else:
            result.append(c)
        i += 1
    return "".join(result)


SIGN_OFF = f"Best Regards,\n{SENDER_NAME}"


# ═══════════════════════════════════════════════════════════════════════════
# ORIGINAL EMAIL
# ═══════════════════════════════════════════════════════════════════════════

def generate_original(first_name, contact_title, company_name,
                      company_website, signal_title, why_relevant):

    system = """You are a senior B2B sales professional at Strikin, a PropTech platform in India.
You write highly personalized, professional cold outreach emails to real estate decision-makers.
Your emails are warm, specific, and always end with a clean sign-off."""

    prompt = f"""Write a complete professional cold outreach email:

RECIPIENT:
  Name:    {first_name}
  Title:   {contact_title}
  Company: {company_name}
  Website: {company_website}

WHY WE ARE REACHING OUT:
  Signal:    {signal_title}
  Relevance: {why_relevant}

ABOUT STRIKIN:
  Strikin is a PropTech platform helping real estate companies in India digitize operations —
  lead management, automated workflows, agent performance tracking, real-time dashboards.
  Clients reduce manual work by 60% and close deals 2x faster.

EMAIL STRUCTURE:
  Line 1:   Dear {first_name},

  Paragraph 1 (2-3 sentences):
    Reference their specific signal ({signal_title}) concretely and naturally.
    Show you understand exactly what they are working on right now.

  Paragraph 2 (2-3 sentences):
    Explain how Strikin directly helps their situation.
    Include one specific metric or benefit (e.g. "60% reduction in manual ops").

  Paragraph 3 (1-2 sentences):
    Soft CTA — propose a 15-minute call. Easy, low-pressure.

  Sign-off (exactly):
    Best Regards,
    {SENDER_NAME}

STRICT RULES:
  - Subject: under 10 words, specific to their company or signal
  - NO "I hope this email finds you well"
  - NO "I came across your company"
  - NO "just wanted to reach out"
  - NO bullet points in body
  - Body: 120-180 words (NOT counting sign-off)
  - Use \\n for paragraph breaks in JSON body field

OUTPUT ONLY this JSON — no markdown, nothing else:
{{"subject": "subject here", "body": "Dear {first_name},\\n\\n[para1]\\n\\n[para2]\\n\\n[para3]\\n\\nBest Regards,\\n{SENDER_NAME}"}}"""

    for attempt in range(3):
        try:
            response = call_ai(prompt, system, max_tokens=800)
            response = _sanitize_json(response)
            data     = json.loads(response)
            if "subject" in data and "body" in data:
                if "Best Regards" not in data["body"]:
                    data["body"] += f"\n\n{SIGN_OFF}"
                return data
        except Exception as e:
            print(f"     ❌ Original failed (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(3)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# FOLLOWUP EMAILS
# ═══════════════════════════════════════════════════════════════════════════

def generate_followup(first_name, company_name, original_subject, followup_num, days):

    angles = {
        1: f"""Sending 3 days after original email.
Angle: Add genuine value — share a relevant PropTech insight or India real estate stat
directly relevant to {company_name}'s situation. Reference original email briefly.
Length: 3 paragraphs, 100-130 words (not counting sign-off).""",

        2: f"""Sending 7 days after original email.
Angle: Try a completely different approach. Acknowledge they are busy.
Offer something concrete and free — a quick demo, free workflow audit,
or case study of a similar India real estate company using Strikin.
Length: 3 short paragraphs, 80-110 words (not counting sign-off).""",

        3: f"""Sending 14 days after original email. Final outreach.
Angle: Be gracious. Say you will stop reaching out after this.
Wish them genuine success. Leave door permanently open — no pitch, no CTA.
Length: 2-3 short paragraphs, 60-80 words (not counting sign-off).""",
    }

    system = """You are a senior B2B sales professional at Strikin, a PropTech platform.
You write warm, professional followup emails. Every email has proper greeting and sign-off."""

    prompt = f"""Write followup #{followup_num} for this lead:

RECIPIENT: {first_name} at {company_name}
ORIGINAL SUBJECT: {original_subject}

INSTRUCTIONS:
{angles[followup_num]}

EMAIL STRUCTURE:
  Line 1:  Dear {first_name},
  [paragraphs as described]
  Sign-off (exactly):
    Best Regards,
    {SENDER_NAME}

RULES:
  - Subject: "Re: {original_subject}"
  - NO "per my previous email"
  - NO "just circling back"
  - NO "following up on my last email"
  - NO bullet points
  - Use \\n for paragraph breaks in JSON body field

OUTPUT ONLY this JSON — no markdown, nothing else:
{{"subject": "Re: {original_subject}", "body": "Dear {first_name},\\n\\n[paragraphs]\\n\\nBest Regards,\\n{SENDER_NAME}"}}"""

    for attempt in range(3):
        try:
            response = call_ai(prompt, system, max_tokens=600)
            response = _sanitize_json(response)
            data     = json.loads(response)
            if "subject" in data and "body" in data:
                if "Best Regards" not in data["body"]:
                    data["body"] += f"\n\n{SIGN_OFF}"
                return data
        except Exception as e:
            print(f"     ❌ Followup {followup_num} failed (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(3)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# BATCH RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_email_generator():
    print("\n✉️  AI EMAIL GENERATOR")
    print("="*55)

    leads = get_leads_needing_email_gen()
    if not leads:
        all_with_email = get_leads_with_email()
        if not all_with_email:
            print("  ⚠️  No leads with email addresses. Run 2a first.")
        else:
            print(f"  ✅ All {len(all_with_email)} leads already have emails generated.")
        return

    print(f"  Generating for {len(leads)} leads (original + 3 followups each)...")
    print("="*55)

    generated = 0
    failed    = 0

    for lead in leads:
        (lead_id, company_name, contact_name, contact_title,
         contact_email, urgency_score, company_website,
         signal_title, why_relevant) = lead

        print(f"\n  ✉️  {company_name} → {contact_name} <{contact_email}>")
        first_name = contact_name.split()[0] if contact_name not in ["Not found","TBD"] else "there"

        orig = generate_original(first_name, contact_title, company_name,
                                 company_website, signal_title, why_relevant)
        if not orig:
            print(f"     ❌ Skipping — original failed")
            failed += 1
            continue

        email_id = save_email(lead_id, company_name, contact_name, contact_email,
                              orig["subject"], orig["body"], "original")
        print(f"     ✅ Original  — {orig['subject']}")

        for fu_num, days in [(1,3),(2,7),(3,14)]:
            fu = generate_followup(first_name, company_name,
                                   orig["subject"], fu_num, days)
            if fu:
                save_email(lead_id, company_name, contact_name, contact_email,
                           fu["subject"], fu["body"], f"followup_{fu_num}",
                           thread_id=str(email_id))
                print(f"     ✅ Followup {fu_num} — {fu['subject']}")
            else:
                print(f"     ⚠️  Followup {fu_num} — failed")

        generated += 1
        wait("between_leads")

    try:
        from agents.excel_writer import build_leads_xlsx
        build_leads_xlsx()
        print(f"\n  ✅ Excel updated → output/leads.xlsx")
    except Exception as e:
        print(f"\n  ⚠️  Excel update: {e}")

    print(f"\n{'─'*55}")
    print(f"  Generated: {generated} sequences ({generated*4} emails)")
    print(f"  Failed:    {failed}")
    print(f"{'─'*55}")
    print(f"  → Run option 3 to send via Discord bot")