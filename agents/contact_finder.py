"""
contact_finder.py — Contact Discovery Engine
=============================================

WEBSITE LOGIC:
  3 queries tried in order
  STRICT: full company slug must appear in domain
  Prefer full slug over primary word (avoids centurylink for century21)
  Strip all subpages → homepage only
  Skip 50+ news/PR/aggregator/social sites

LINKEDIN LOGIC:
  Priority: CEO → Co-Founder → Founder → CTO → MD → Head of Tech
  Query uses primary role keyword (not label) for better search matching
  Collects top 10 results, SCORES each candidate:
    +3 role match in snippet
    +2 company name match
    +1 founder/executive keyword bonus
  Returns highest scoring candidate (not just first match)
  Fallback query: "{company} CEO linkedin" (no site: operator)

NAME PARSING:
  Strict: 2-4 words, capitalized, no digits, no special chars
  Handles: " - " / " – " / " — " / " | " separators
  Stops title at: @, " at ", ", with ", " and ", double space
  Max title 50 chars

SKIP PROCESSING:
  Leads already with contacts → skipped (no redundant searches)
"""

import re
import time
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
from utils.database import get_all_leads, update_lead_contact
from agents.excel_writer import write_contact_to_row
from utils.rate_limiter import wait


# ── Role priority: (search_keyword, validation_keywords) ─────────────────
ROLE_PRIORITY = [
    ("CEO",               ["ceo", "chief executive"]),
    ("Co-Founder",        ["co-founder", "cofounder", "co founder"]),
    ("Founder",           ["founder"]),
    ("CTO",               ["cto", "chief technology", "chief technical"]),
    ("Managing Director", ["managing director"]),
    ("Head of Technology",["head of tech", "vp engineering", "vp tech"]),
]

# ── Strict role keywords for title validation ─────────────────────────────
VALID_TITLE_KEYWORDS = [
    "ceo", "chief executive",
    "cto", "chief technology", "chief technical",
    "founder", "co-founder", "cofounder",
    "managing director",
    "head of technology", "head of tech",
    "vp engineering", "vp technology",
    "president", "general manager",
    "chief operating", "coo",
]

# These must NOT appear in title — blocks mentor, advisor, investor roles
INVALID_TITLE_KEYWORDS = [
    "mentor", "advisor", "investor", "consultant", "coach",
    "board member", "angel", "speaker", "professor", "teacher",
    "volunteer", "intern", "specialist", "analyst", "associate",
    "manager of", "head of marketing", "head of sales",
    "vp sales", "vp marketing", "vp growth", "director of sales",
    "director of marketing",
]

# ── Sites to skip for website search ─────────────────────────────────────
SKIP_SITES = [
    # Social
    "linkedin.", "facebook.", "twitter.", "instagram.", "x.com", "youtube.",
    "tiktok.", "pinterest.", "reddit.",
    # News & media
    "bloomberg.", "techcrunch.", "reuters.", "forbes.", "businessinsider.",
    "economictimes.", "livemint.", "moneycontrol.", "business-standard.",
    "timesofindia.", "ndtv.", "thehindu.", "inc42.", "yourstory.",
    "entrackr.", "venturebeat.", "medianama.", "scroll.in",
    "republicworld.", "republicnewsindia.", "outlookindia.",
    "deccanherald.", "tribuneindia.", "theweek.", "thewire.",
    "hindustantimes.", "financialexpress.", "cnbc.", "cnbctv18.",
    # PR / Press release sites
    "issuewire.", "prweb.", "einpresswire.", "globenewswire.",
    "accesswire.", "newswire.", "pr.com", "businesswire.",
    "prnewswire.", "markets.businessinsider.", "finance.yahoo.",
    # PR tools
    "prowly.", "prezly.", "meltwater.", "cision.", "muck-rack.",
    # Blog platforms
    "medium.com", "substack.", "blogspot.", "wordpress.",
    # Aggregators / databases
    "wikipedia.", "crunchbase.", "pitchbook.", "tracxn.", "owler.",
    "zoominfo.", "glassdoor.", "indeed.", "ambitionbox.", "comparably.",
    "justdial.", "indiamart.", "tradeindia.", "zaubacorp.", "tofler.",
    "investing.com", "tripadvisor.", "yelp.", "trustpilot.",
    "stockanalysis.", "macrotrends.", "wisesheets.",
    # Search engines
    "google.", "bing.", "yahoo.", "duckduckgo.",
    # Misc
    "aginternetwork.", "agoraindex.",
]


# ═══════════════════════════════════════════════════════════════════════════
# WEBSITE FINDER
# ═══════════════════════════════════════════════════════════════════════════

def find_company_website(company_name):
    """
    Finds official company homepage.

    MATCHING PRIORITY (fixes centurylink vs century21 problem):
      1. Full slug match: "century21" in "century21.com" ← strongest
      2. Primary word match: "century" in "century21.com" ← weaker fallback

    HOMEPAGE STRIPPING:
      https://spintly.com/about-us → https://spintly.com

    FAKE DOMAIN PROTECTION:
      Domain must START with company slug or be close match
      "openai-news.com" rejected for "openai" (has hyphen)
    """
    # Build slugs
    words        = company_name.lower().split()
    primary      = words[0].replace("-","").replace(".","").replace(" ","")
    full_slug    = company_name.lower().replace(" ","").replace("-","")[:12]

    queries = [
        f'"{company_name}" official website',
        f"{company_name} company website",
        f"{company_name} proptech",
        f"{company_name} startup platform",
    ]

    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10))

            # Pass 1 — full slug in domain (strongest, prevents wrong matches)
            for r in results:
                url = r.get("href", "")
                if not url or any(s in url.lower() for s in SKIP_SITES):
                    continue
                domain = get_domain(url)
                if full_slug[:8] in domain:
                    return get_homepage(url)

            # Pass 2 — primary word starts domain root (no hyphens = no fakes)
            # "spintly-fake.com" → domain_root="spintly-fake" has hyphen → rejected
            for r in results:
                url = r.get("href", "")
                if not url or any(s in url.lower() for s in SKIP_SITES):
                    continue
                domain      = get_domain(url)
                domain_root = domain.split(".")[0]
                if domain_root.startswith(primary) and "-" not in domain_root:
                    return get_homepage(url)

            wait("ddg_search")

        except Exception:
            wait("ddg_error")
            continue

    return None


def get_domain(url):
    """https://www.spintly.com/about → spintly.com"""
    try:
        d = url.lower().split("/")[2]
        return d.replace("www.", "")
    except Exception:
        return url.lower()


def get_homepage(url):
    """https://spintly.com/about-us → https://spintly.com"""
    try:
        p = url.split("/")
        return f"{p[0]}//{p[2]}"
    except Exception:
        return url


# ═══════════════════════════════════════════════════════════════════════════
# LINKEDIN FINDER — SCORING BASED
# ═══════════════════════════════════════════════════════════════════════════

def find_linkedin_contact(company_name):
    """
    Finds best LinkedIn contact using scoring instead of first-match.

    SCORING PER RESULT:
      +3 — searched role keyword found in snippet
      +2 — company name found in snippet
      +1 — founder/executive bonus keyword

    Returns highest scoring valid candidate across all role searches.
    Falls back to broader query if site: operator finds nothing.
    """
    # Normalize company slug for matching
    company_slug = company_name.lower().replace(" ", "")

    best_result = None
    best_score  = 0

    for role_label, role_keywords in ROLE_PRIORITY:
        # Use primary keyword in query (not label) — better search matching
        search_keyword = role_keywords[0]

        # Primary query: site: operator
        queries = [
            f'site:linkedin.com/in "{company_name}" {search_keyword}',
            f'site:linkedin.com/in "{company_name}" real estate {search_keyword}',
            f'{company_name} real estate {search_keyword} linkedin',
        ]

        for query in queries:
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=10))

                for r in results:
                    url  = r.get("href", "")
                    title_text = r.get("title", "")
                    body = r.get("body", "")

                    if "linkedin.com/in/" not in url:
                        continue

                    combined = (title_text + " " + body).lower()
                    combined_slug = combined.replace(" ", "")

                    # Score this candidate
                    score = 0

                    # +3 role match
                    if any(kw in combined for kw in role_keywords):
                        score += 3

                    # +2 company name match (slug-based)
                    # Also check full company name appears verbatim
                    if company_slug[:6] in combined_slug:
                        score += 2
                    # Bonus +2 if EXACT company name in snippet (high confidence)
                    if company_name.lower() in combined:
                        score += 2

                    # +1 founder/executive bonus
                    if any(kw in combined for kw in ["founder", "executive", "chief"]):
                        score += 1

                    # Must have minimum score to be considered
                    if score < 4:
                        continue

                    # Parse name + title
                    parsed = parse_snippet(title_text, company_name)
                    if not parsed:
                        parsed = parse_snippet(body, company_name)
                    if not parsed:
                        continue

                    if score > best_score:
                        best_score  = score
                        best_result = {
                            "contact_name":  parsed["name"],
                            "contact_title": parsed["title"],
                            "linkedin_url":  clean_url(url),
                            "score":         score,
                        }

                wait("ddg_search")

            except Exception:
                wait("ddg_error")
                continue

        # If we already found a high-confidence result → stop early
        if best_score >= 5:
            break

    return best_result


def parse_snippet(text, company_name):
    """
    Extracts name + title from LinkedIn search snippet.

    Handles separators: " - " / " – " / " — " / " | "
    NAME: 2-4 words, capitalized, no digits, no special chars
    TITLE: stops at @/" at "/" and "/" with "/connectors, max 50 chars
           must contain valid role keyword
    """
    if not text or len(text) < 5:
        return None

    # Clean suffixes
    for suffix in ["| LinkedIn", "- LinkedIn", "· LinkedIn", "LinkedIn"]:
        text = text.replace(suffix, "")
    text = text.strip()

    # Remove snippet cutoff
    if "..." in text:
        text = text.split("...")[0].strip()

    # Split into parts — now includes em dash " — "
    parts = None
    for sep in [" - ", " – ", " — ", " | "]:
        candidate = [p.strip() for p in text.split(sep) if p.strip()]
        if len(candidate) >= 2:
            parts = candidate
            break

    if not parts or len(parts) < 2:
        return None

    name  = parts[0].strip()
    title = parts[1].strip()

    # ── Clean name ────────────────────────────────────────────────────────
    if "," in name:
        name = name.split(",")[0].strip()

    # Remove company name trailing word from name
    for word in company_name.split():
        if len(word) > 3 and name.lower().endswith(word.lower()):
            name = name[:name.lower().rfind(word.lower())].strip()

    # ── Clean title ───────────────────────────────────────────────────────
    stop_patterns = ["@", " | ", " · ", ";", " at ", ", with ", " and ", "/"]
    for stop in stop_patterns:
        if stop in title:
            title = title.split(stop)[0].strip()

    # Remove company name from end of title
    for word in company_name.split():
        if len(word) > 3 and title.lower().endswith(word.lower()):
            title = title[:title.lower().rfind(word.lower())].strip()

    # Remove trailing person names (e.g. "Founder Rakesh Lodhi" → "Founder")
    # If title ends with two capitalized words that look like a name → strip them
    title_words = title.split()
    if len(title_words) >= 3:
        last_two = title_words[-2:]
        if (all(w[0].isupper() for w in last_two if w)
                and not any(kw in " ".join(last_two).lower()
                           for kw in ["ceo","cto","coo","officer","director","founder","president"])):
            title = " ".join(title_words[:-2]).strip()

    title = title.strip(" -–—&.,/()")

    # Cap at 50 chars
    if len(title) > 50:
        title = title[:50].rsplit(" ", 1)[0].strip()

    # ── Validate name ─────────────────────────────────────────────────────
    words = name.split()
    if len(words) < 2 or len(words) > 4:
        return None
    if any(c.isdigit() for c in name):
        return None
    if any(c in name for c in ["@","http","{","}","·","|","/"]):
        return None
    if name.isupper():
        return None
    for w in words:
        w = w.strip(".,-()")
        if w and not w[0].isupper():
            return None

    # ── Validate title ────────────────────────────────────────────────────
    if not any(kw in title.lower() for kw in VALID_TITLE_KEYWORDS):
        return None
    # Block mentor/advisor/non-exec roles
    if any(kw in title.lower() for kw in INVALID_TITLE_KEYWORDS):
        return None
    if len(title) < 2:
        return None

    return {"name": name, "title": title}


def clean_url(url):
    """Clean to https://www.linkedin.com/in/username"""
    match = re.search(r'linkedin\.com/in/([\w\-]+)', url)
    if match:
        return f"https://www.linkedin.com/in/{match.group(1)}"
    return url


def build_fallback_url(company_name):
    """LinkedIn search URL fallback."""
    q = company_name.replace(" ", "%20")
    return f"https://www.linkedin.com/search/results/people/?keywords={q}%20CEO"


# ═══════════════════════════════════════════════════════════════════════════
# MASTER RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def find_all_contacts():
    print("\n🔍 CONTACT FINDER STARTING")
    print("="*55)

    leads = get_all_leads()
    if not leads:
        print("  ⚠️  No leads in DB")
        return []

    print(f"  Finding contacts for {len(leads)} leads...")
    print("="*55)

    updated       = []
    found_count   = 0
    website_count = 0
    skipped_count = 0

    for lead in leads:
        lead_id      = lead[0]
        company_name = lead[1]
        # Check existing contact columns
        existing_contact = lead[9] if len(lead) > 9 else None

        # Skip multi-company entries
        if "," in company_name and len(company_name) > 25:
            print(f"\n  ⏭️  Skipping multi-company: {company_name}")
            continue

        # Skip already processed leads (not TBD/Not found)
        if existing_contact and existing_contact not in ["TBD", "Not found", None]:
            print(f"\n  ✅ Already found: {company_name} — {existing_contact}")
            skipped_count += 1
            found_count   += 1
            continue

        print(f"\n  🔎 {company_name}...")

        # Website
        website = find_company_website(company_name)
        if website:
            print(f"     🌐 {website}")
            website_count += 1
        else:
            print(f"     ⚠️  Website not found")
            website = "Not found"

        wait("between_companies")

        # LinkedIn
        contact = find_linkedin_contact(company_name)
        if contact:
            contact_name  = contact["contact_name"]
            contact_title = contact["contact_title"]
            linkedin_url  = contact["linkedin_url"]
            print(f"     👤 {contact_name} — {contact_title}")
            print(f"     🔗 {linkedin_url}")
            found_count += 1
        else:
            contact_name  = "Not found"
            contact_title = "Not found"
            linkedin_url  = build_fallback_url(company_name)
            print(f"     ⚠️  Contact not found — search URL fallback")

        wait("between_leads")

        update_lead_contact(lead_id, {
            "contact_name":    contact_name,
            "contact_title":   contact_title,
            "company_website": website,
            "linkedin_url":    linkedin_url,
        })

        # ── Write to Excel immediately ────────────────────────────────────
        write_contact_to_row(company_name, {
            "contact_name":    contact_name,
            "contact_title":   contact_title,
            "company_website": website,
            "linkedin_url":    linkedin_url,
        })

        updated.append({
            "company_name":    company_name,
            "contact_name":    contact_name,
            "contact_title":   contact_title,
            "company_website": website,
            "linkedin_url":    linkedin_url,
        })

    print(f"\n{'─'*55}")
    print(f"📊 CONTACT FINDER SUMMARY")
    print(f"{'─'*55}")
    print(f"  Total leads:      {len(leads)}")
    print(f"  Already had:      {skipped_count}")
    print(f"  Websites found:   {website_count}")
    print(f"  Contacts found:   {found_count}")
    print(f"  Not found:        {len(leads) - found_count}")
    print(f"{'─'*55}")

    return updated