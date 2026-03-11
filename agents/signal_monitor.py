"""
signal_monitor.py — Signal Collection Engine
=============================================
Collects raw signals from 3 sources:

  SOURCE 1: Google News RSS
    WHY: Wide net — catches global funding, launch, transformation signals
    HOW: feedparser reads Google News RSS URL built with keywords

  SOURCE 2: PropTech News Sites RSS
    WHY: Industry depth — every PropTech article regardless of popularity
    HOW: feedparser reads Inman, Propmodo, HousingWire RSS feeds

  SOURCE 3: Real Estate News Sites
    WHY: Broader real estate company news — global + India mixed
    HOW: feedparser reads The Ken, CRE Herald, Livemint, Financial Post

FILTER LOGIC (applied to every article):
  CHECK 1 → Is URL already in DB? YES = skip (already processed)
  CHECK 2 → Is article within time window? NO = skip (too old)
  Both pass = NEW article = process it

TIME WINDOW:
  First run  → last 14 days (DB empty, need historical data)
  Later runs → last_run_timestamp to NOW (only genuinely new articles)
"""

import feedparser
import re
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser

from utils.database import (
    is_already_processed,
    get_last_run_timestamp,
    get_processed_count
)


# ═══════════════════════════════════════════════════════════════════════════
# KEYWORDS — Google News search terms
# Each keyword targets a specific buying signal type
# ═══════════════════════════════════════════════════════════════════════════
GOOGLE_NEWS_KEYWORDS = [
    "proptech launch india",           # company actively building RIGHT NOW
    "real estate digital transformation",  # exact decision-making moment
    "real estate platform funding",    # funding = budget exists RIGHT NOW
    "property tech startup",           # new startups need everything
    "real estate CRM adoption",        # direct buying signal
    "real estate app launch",          # building app = needs tools urgently
    "proptech india funding 2025",     # India-specific fresh signals
    "real estate startup india",       # Indian first-time buyers
]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 2: PropTech News Sites
# ═══════════════════════════════════════════════════════════════════════════
PROPTECH_SITE_FEEDS = [
    {
        "name": "Inman Technology",
        "url": "https://www.inman.com/category/technology/feed/",
        "why": "Leading real estate tech news"
    },
    {
        "name": "Propmodo",
        "url": "https://www.propmodo.com/feed/",
        "why": "Pure PropTech analysis and company news"
    },
    {
        "name": "HousingWire PropTech",
        "url": "https://www.housingwire.com/tag/proptech/feed/",
        "why": "PropTech tag specific feed"
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 3: Real Estate News Sites
# ═══════════════════════════════════════════════════════════════════════════
COMPANY_BLOG_FEEDS = [
    {
        "name": "The Ken Real Estate",
        "url": "https://the-ken.com/tag/real-estate/feed/",
        "why": "Deep India business journalism"
    },
    {
        "name": "CRE Herald",
        "url": "https://creherald.com/feed",
        "why": "Commercial real estate company news"
    },
    {
        "name": "Livemint Companies",
        "url": "https://www.livemint.com/rss/companies",
        "why": "India top financial paper"
    },
    {
        "name": "Financial Post Real Estate",
        "url": "https://financialpost.com/category/real-estate/feed",
        "why": "Commercial real estate breaking news"
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# TIME WINDOW — Core filtering logic
# ═══════════════════════════════════════════════════════════════════════════

def get_time_window():
    """
    Returns cutoff datetime for article filtering.

    HOW IT WORKS:
      First run ever  → DB empty (processed_count = 0)
                      → window = 14 days ago
                      → fetches historical data to seed the DB

      Every run after → DB has URLs
                      → window = last_run_timestamp
                      → fetches only articles published since last run
                      → e.g. if last run was 9AM, gets only 9AM to NOW

    WHY THIS IS CORRECT:
      Run 1 → 14 days of articles
      Run 2 → only articles from last 24 hours (new ones only)
      Run 3 → only articles from last 24 hours (new ones only)
      No overlap, no missed articles, no wasted processing
    """
    is_first_run = get_processed_count() == 0

    if is_first_run:
        window = datetime.now(timezone.utc) - timedelta(days=14)
        print(f"  📅 First run — fetching last 14 days")
    else:
        last_run_str = get_last_run_timestamp()
        try:
            window = dateparser.parse(last_run_str)
            if window.tzinfo is None:
                window = window.replace(tzinfo=timezone.utc)
            print(f"  📅 Fetching since last run: {last_run_str} UTC")
        except Exception:
            # Fallback to 14 days if timestamp is corrupted
            window = datetime.now(timezone.utc) - timedelta(days=14)
            print(f"  📅 Fallback — fetching last 14 days")

    return window


def is_within_window(entry, window):
    """
    CHECK 2 — Time window filter.
    Returns True if article published AFTER window cutoff.
    Returns True if no date found (safer to include than miss).

    Only runs if CHECK 1 (DB check) passes first.
    """
    article_date = parse_published_date(entry)
    if not article_date:
        return True  # no date = include it, safer to process than miss
    return article_date > window


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def parse_published_date(entry):
    """
    Extracts and parses published date from RSS entry.
    Handles all date formats across different RSS feeds.
    Returns timezone-aware datetime in UTC, or None if unparseable.
    """
    date_str = (
        getattr(entry, "published", None) or
        getattr(entry, "updated", None) or
        getattr(entry, "created", None)
    )

    if not date_str:
        return None

    try:
        parsed = dateparser.parse(date_str)
        if parsed and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def clean_title(title):
    """Strips whitespace from title."""
    if not title:
        return "No title"
    return title.strip()


def clean_summary(summary):
    """
    Removes HTML tags from RSS summary.
    Limits to 500 chars — enough context for Gemini classifier.
    """
    if not summary:
        return "No summary available"
    clean = re.sub(r'<[^>]+>', '', summary)
    return clean.strip()[:500]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 1: GOOGLE NEWS RSS
# ═══════════════════════════════════════════════════════════════════════════

def fetch_google_news(window):
    """
    Fetches articles from Google News RSS for all keywords.

    FILTER ORDER PER ARTICLE:
      1. CHECK 1 → is URL in DB? YES = skip
      2. CHECK 2 → is article within time window? NO = skip
      3. Both pass = new article = add to signals

    No slice limit — iterate all entries so no articles are missed.
    """
    signals = []

    for keyword in GOOGLE_NEWS_KEYWORDS:
        try:
            encoded_keyword = keyword.replace(" ", "+")
            url = (
                f"https://news.google.com/rss/search?"
                f"q={encoded_keyword}&hl=en-IN&gl=IN&ceid=IN:en"
            )

            feed = feedparser.parse(url)

            if feed.bozo and not feed.entries:
                continue

            for entry in feed.entries:  # no slice — iterate all

                url_link = getattr(entry, "link", "")

                # CHECK 1 — DB check first (fastest)
                if is_already_processed(url_link):
                    continue

                # CHECK 2 — time window check second
                if not is_within_window(entry, window):
                    continue

                # Both passed — new article
                signal = {
                    "title":     clean_title(getattr(entry, "title", "")),
                    "summary":   clean_summary(getattr(entry, "summary", "")),
                    "url":       url_link,
                    "source":    "google_news",
                    "keyword":   keyword,
                    "published": str(parse_published_date(entry) or "unknown")
                }
                signals.append(signal)

        except Exception:
            continue

    print(f"  📊 Google News: {len(signals)} new signals")
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 2: PROPTECH NEWS SITES RSS
# ═══════════════════════════════════════════════════════════════════════════

def fetch_proptech_sites(window):
    """
    Fetches from PropTech news site RSS feeds.

    FILTER ORDER PER ARTICLE:
      1. CHECK 1 → is URL in DB? YES = skip
      2. CHECK 2 → is article within time window? NO = skip
      3. Both pass = new article = add to signals

    No slice limit — iterate all entries.
    """
    signals = []

    for site in PROPTECH_SITE_FEEDS:
        try:
            feed = feedparser.parse(site["url"])

            if feed.bozo and not feed.entries:
                print(f"  ⚠️  Could not fetch: {site['name']}")
                continue

            for entry in feed.entries:  # no slice — iterate all

                url_link = getattr(entry, "link", "")

                # CHECK 1 — DB check first
                if is_already_processed(url_link):
                    continue

                # CHECK 2 — time window check
                if not is_within_window(entry, window):
                    continue

                signal = {
                    "title":     clean_title(getattr(entry, "title", "")),
                    "summary":   clean_summary(getattr(entry, "summary", "")),
                    "url":       url_link,
                    "source":    "proptech_site",
                    "keyword":   site["name"],
                    "published": str(parse_published_date(entry) or "unknown")
                }
                signals.append(signal)

        except Exception:
            print(f"  ⚠️  Could not fetch: {site['name']}")
            continue

    print(f"  📊 PropTech Sites: {len(signals)} new signals")
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 3: REAL ESTATE NEWS SITES RSS
# ═══════════════════════════════════════════════════════════════════════════

def fetch_company_blogs(window):
    """
    Fetches from real estate news site RSS feeds.

    FILTER ORDER PER ARTICLE:
      1. CHECK 1 → is URL in DB? YES = skip
      2. CHECK 2 → is article within time window? NO = skip
      3. Both pass = new article = add to signals

    No slice limit — iterate all entries.
    """
    signals = []

    for blog in COMPANY_BLOG_FEEDS:
        try:
            feed = feedparser.parse(blog["url"])

            if feed.bozo and not feed.entries:
                print(f"  ⚠️  Could not fetch: {blog['name']}")
                continue

            for entry in feed.entries:  # no slice — iterate all

                url_link = getattr(entry, "link", "")

                # CHECK 1 — DB check first
                if is_already_processed(url_link):
                    continue

                # CHECK 2 — time window check
                if not is_within_window(entry, window):
                    continue

                signal = {
                    "title":     clean_title(getattr(entry, "title", "")),
                    "summary":   clean_summary(getattr(entry, "summary", "")),
                    "url":       url_link,
                    "source":    "realestate_news",
                    "keyword":   blog["name"],
                    "published": str(parse_published_date(entry) or "unknown")
                }
                signals.append(signal)

        except Exception:
            print(f"  ⚠️  Could not fetch: {blog['name']}")
            continue

    print(f"  📊 Real Estate Sites: {len(signals)} new signals")
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# MASTER COLLECTOR — combines all 3 sources
# ═══════════════════════════════════════════════════════════════════════════

def collect_all_signals():
    """
    Main function called from main.py.
    Runs all 3 sources, combines results, removes URL duplicates.

    DEDUPLICATION:
      URL checked against DB before processing (CHECK 1)
      URL checked against seen_urls set for cross-source duplicates
      Same article from 2 sources = kept only once
    """
    print("\n" + "="*55)
    print("🚀 LEAD GEN AGENT — SIGNAL COLLECTION")
    print("="*55)

    # Calculate time window ONCE — passed to all fetchers
    window = get_time_window()

    # Fetch from all 3 sources
    google_signals   = fetch_google_news(window)
    proptech_signals = fetch_proptech_sites(window)
    blog_signals     = fetch_company_blogs(window)

    # Combine all signals
    all_signals = google_signals + proptech_signals + blog_signals

    # Remove cross-source URL duplicates
    # Same article appearing in 2 sources = keep only first occurrence
    seen_urls = set()
    unique_signals = []

    for signal in all_signals:
        url = signal.get("url", "").rstrip("/")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_signals.append(signal)

    duplicates_removed = len(all_signals) - len(unique_signals)

    # Print clean summary
    print("─"*55)
    print(f"  Google News:      {len(google_signals)}")
    print(f"  PropTech Sites:   {len(proptech_signals)}")
    print(f"  Real Estate News: {len(blog_signals)}")
    print(f"  ───────────────────────────")
    print(f"  Total:            {len(all_signals)}")
    if duplicates_removed > 0:
        print(f"  Duplicates:       {duplicates_removed} removed")
    print(f"  New signals:      {len(unique_signals)}")
    print("─"*55)

    if len(unique_signals) == 0:
        print("  ℹ️  No new signals since last run")

    return unique_signals