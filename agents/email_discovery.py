"""
email_discovery.py — Auto Email Discovery
==========================================
3-step approach per lead:

  Step 1 — Google search for public email
           Query: "Name" company email site:company.com
           Regex extract from snippets

  Step 2 — Website scan (contact/team/about pages)
           Fetch page → regex extract emails
           Skip generic: info@, support@, hello@, admin@

  Step 3 — Pattern generation (best guess)
           first@domain, first.last@domain, f.last@domain
           Stored with confidence: high/medium/low

Saves discovered email to raw_leads.contact_email
"""

import re
import time
import requests
from utils.rate_limiter import wait
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from utils.database import get_all_leads, update_lead_email
from agents.excel_writer import write_email_to_row

# Generic emails to reject
GENERIC_EMAILS = [
    "info@", "support@", "hello@", "admin@", "contact@",
    "team@", "hr@", "careers@", "jobs@", "noreply@",
    "no-reply@", "help@", "sales@", "press@", "media@",
    "enquiries@", "enquiry@", "office@",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def is_generic(email):
    return any(email.lower().startswith(g) for g in GENERIC_EMAILS)


def is_valid_email(email, domain=None):
    """Basic validation + optional domain check."""
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return False
    if is_generic(email):
        return False
    # Reject obviously fake patterns
    if any(x in email.lower() for x in ["example", "test@", "email@", "user@"]):
        return False
    # If domain given, prefer matching domain
    if domain:
        email_domain = email.split("@")[1].lower()
        website_domain = domain.lower().replace("www.", "").replace("https://", "").split("/")[0]
        return email_domain in website_domain or website_domain in email_domain
    return True


# ─────────────────────────────────────────────────────────────────────────
# STEP 1 — DDG search for public email
# ─────────────────────────────────────────────────────────────────────────

def search_email_online(contact_name, company_name, company_website):
    """
    Searches DDG for publicly listed email address.
    Returns email string or None.
    """
    domain = ""
    if company_website and company_website != "Not found":
        domain = company_website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]

    queries = [
        f'"{contact_name}" {company_name} email',
        f'"{contact_name}" "{domain}" email' if domain else None,
        f'site:{domain} "{contact_name}"' if domain else None,
    ]
    queries = [q for q in queries if q]

    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))

            for r in results:
                text = (r.get("title", "") + " " + r.get("body", ""))
                emails = EMAIL_REGEX.findall(text)
                for em in emails:
                    if is_valid_email(em, domain):
                        return em, "high"

            wait("ddg_search")
        except Exception:
            wait("ddg_error")
            continue

    return None, None


# ─────────────────────────────────────────────────────────────────────────
# STEP 2 — Scan company website pages
# ─────────────────────────────────────────────────────────────────────────

def scan_website_for_email(company_website, contact_name=None):
    """
    Fetches contact/team/about pages and extracts emails.
    Returns email string or None.
    """
    if not company_website or company_website == "Not found":
        return None, None

    base = company_website.rstrip("/")
    pages = [
        base,
        f"{base}/contact",
        f"{base}/contact-us",
        f"{base}/team",
        f"{base}/about",
        f"{base}/about-us",
    ]

    domain = base.replace("https://", "").replace("http://", "").replace("www.", "")
    first_name = contact_name.split()[0].lower() if contact_name and contact_name != "Not found" else None

    for page_url in pages:
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                continue

            emails = EMAIL_REGEX.findall(resp.text)
            personal = []
            generic  = []

            for em in set(emails):
                em = em.lower()
                if not is_valid_email(em, domain):
                    continue
                # Prefer email containing first name
                if first_name and first_name in em:
                    return em, "high"
                if not is_generic(em):
                    personal.append(em)
                else:
                    generic.append(em)

            if personal:
                return personal[0], "medium"

            wait("scrape")

        except Exception:
            continue

    return None, None


# ─────────────────────────────────────────────────────────────────────────
# STEP 3 — Generate email patterns
# ─────────────────────────────────────────────────────────────────────────

def generate_email_pattern(contact_name, company_website):
    """
    Generates most likely email pattern from name + domain.
    Returns best guess email or None.
    """
    if not contact_name or contact_name == "Not found":
        return None, None
    if not company_website or company_website == "Not found":
        return None, None

    # Extract domain
    domain = (company_website
              .replace("https://", "")
              .replace("http://", "")
              .replace("www.", "")
              .split("/")[0]
              .lower())

    parts = contact_name.lower().split()
    if len(parts) < 2:
        return None, None

    first = parts[0]
    last  = parts[-1]

    # Most common patterns in order of likelihood
    patterns = [
        f"{first}.{last}@{domain}",    # john.doe@company.com (most common)
        f"{first}@{domain}",            # john@company.com
        f"{first}{last}@{domain}",      # johndoe@company.com
        f"{first[0]}{last}@{domain}",   # jdoe@company.com
        f"{first}.{last[0]}@{domain}",  # john.d@company.com
    ]

    return patterns[0], "low"


# ─────────────────────────────────────────────────────────────────────────
# MASTER EMAIL DISCOVERY
# ─────────────────────────────────────────────────────────────────────────

def discover_all_emails():
    """
    Runs email discovery for all leads without email.
    Step 1 → Step 2 → Step 3 fallback.
    Saves to DB.
    """
    print("\n📧 EMAIL DISCOVERY STARTING")
    print("="*55)

    leads = get_all_leads()
    if not leads:
        print("  ⚠️  No leads in DB")
        return

    # Filter leads needing email
    needs_email = [
        l for l in leads
        if not l[13] or l[13] in ["", "Not found", "TBD"]
    ]

    if not needs_email:
        print("  ✅ All leads already have emails")
        return

    print(f"  Discovering emails for {len(needs_email)} leads...")
    print("="*55)

    found_high   = 0
    found_medium = 0
    found_low    = 0
    not_found    = 0

    for lead in needs_email:
        lead_id         = lead[0]
        company_name    = lead[1]
        contact_name    = lead[9]
        company_website = lead[11]

        if contact_name in ["Not found", "TBD", ""]:
            print(f"\n  ⏭️  {company_name} — no contact name, skipping")
            not_found += 1
            continue

        print(f"\n  🔎 {company_name} — {contact_name}...")

        email = None
        confidence = None

        # Step 1 — Search online
        email, confidence = search_email_online(contact_name, company_name, company_website)
        if email:
            print(f"     📧 [SEARCH] {email} ({confidence})")
        else:
            # Step 2 — Scan website
            email, confidence = scan_website_for_email(company_website, contact_name)
            if email:
                print(f"     📧 [WEBSITE] {email} ({confidence})")
            else:
                # Step 3 — Pattern generation
                email, confidence = generate_email_pattern(contact_name, company_website)
                if email:
                    print(f"     📧 [PATTERN] {email} ({confidence})")
                else:
                    print(f"     ⚠️  Email not found")
                    not_found += 1
                    continue

        # FIX: strip dirty domain suffix e.g. x@domain.com.Company -> x@domain.com
        import re as _re
        _m = _re.match(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,6}", email)
        email = _m.group(0) if _m else email

        update_lead_email(lead_id, email)

        # ── Write to Excel immediately ────────────────────────────────────
        write_email_to_row(company_name, email, confidence or "")

        if confidence == "high":
            found_high += 1
        elif confidence == "medium":
            found_medium += 1
        else:
            found_low += 1

        wait("between_leads")

    total_found = found_high + found_medium + found_low
    print(f"\n{'─'*55}")
    print(f"📊 EMAIL DISCOVERY SUMMARY")
    print(f"{'─'*55}")
    print(f"  Total processed:  {len(needs_email)}")
    print(f"  Found (high):     {found_high}   ← search/direct")
    print(f"  Found (medium):   {found_medium} ← website scan")
    print(f"  Found (low):      {found_low}    ← pattern guess")
    print(f"  Not found:        {not_found}")
    print(f"  Total found:      {total_found}")
    print(f"{'─'*55}")
    print(f"\n  ⚠️  Low confidence emails are best-guess patterns.")
    print(f"  Verify before sending — edit in Google Sheets if needed.")