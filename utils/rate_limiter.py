"""
rate_limiter.py — Centralized Random Rate Limiting
====================================================

WHY RANDOM DELAYS:
  Fixed delays (e.g. sleep(2)) are detectable by anti-bot systems.
  Random delays mimic human behaviour — harder to detect/block.
  Each call gets a unique float like 3.2847 seconds.

LIMITS BY CATEGORY:
  ┌─────────────────────┬──────────────┬──────────────┬───────────────────┐
  │ Category            │ Min (s)      │ Max (s)      │ Reason            │
  ├─────────────────────┼──────────────┼──────────────┼───────────────────┤
  │ DDG Search          │ 2.5          │ 5.5          │ Anti-bot / block  │
  │ DDG on Error        │ 5.0          │ 10.0         │ Backoff on fail   │
  │ Website Scrape      │ 1.5          │ 4.0          │ Polite crawl      │
  │ Scrape on Error     │ 3.0          │ 7.0          │ Backoff on fail   │
  │ Groq AI             │ 1.0          │ 3.0          │ API rate limit    │
  │ DeepSeek AI         │ 1.5          │ 3.5          │ API rate limit    │
  │ OpenRouter AI       │ 1.5          │ 3.5          │ API rate limit    │
  │ AI on Rate Limit    │ 60.0         │ 90.0         │ Hard backoff      │
  │ AI All Exhausted    │ 90.0         │ 120.0        │ Long wait         │
  │ Email Send (SMTP)   │ 8.0          │ 20.0         │ Gmail anti-spam   │
  │ Email on Error      │ 15.0         │ 35.0         │ Backoff on fail   │
  │ IMAP Check          │ 2.0          │ 5.0          │ Inbox polling     │
  │ Between Leads       │ 3.0          │ 6.0          │ General pacing    │
  └─────────────────────┴──────────────┴──────────────┴───────────────────┘

USAGE:
  from utils.rate_limiter import wait

  wait("ddg_search")         → sleeps 3.2847s (random between 2.5-5.5)
  wait("email_send")         → sleeps 12.7341s (random between 8-20)
  wait("groq")               → sleeps 1.8923s (random between 1-3)
  wait("ddg_error")          → sleeps 7.4512s (random between 5-10)
"""

import time
import random


# ── Rate limit table ──────────────────────────────────────────────────────
LIMITS = {
    # DuckDuckGo search
    "ddg_search":        (2.5,  5.5),
    "ddg_error":         (5.0,  10.0),

    # Website scraping
    "scrape":            (1.5,  4.0),
    "scrape_error":      (3.0,  7.0),

    # AI providers — normal call
    "groq":              (1.0,  3.0),
    "deepseek":          (1.5,  3.5),
    "openrouter":        (1.5,  3.5),
    "ai_generic":        (1.0,  3.0),

    # AI providers — rate limited / backoff
    "ai_rate_limit":     (60.0, 90.0),
    "ai_all_exhausted":  (90.0, 120.0),
    "ai_error":          (2.0,  5.0),

    # Gmail SMTP sending
    "email_send":        (8.0,  20.0),
    "email_error":       (15.0, 35.0),

    # Gmail IMAP checking
    "imap_check":        (2.0,  5.0),

    # Between leads / general pacing
    "between_leads":     (3.0,  6.0),
    "between_companies": (2.0,  5.0),
}

# ── Human-readable labels ────────────────────────────────────────────────
CATEGORY_LABELS = {
    "ddg_search":        "DuckDuckGo search",
    "ddg_error":         "Search error backoff",
    "scrape":            "Website scraping",
    "scrape_error":      "Scrape retry delay",
    "groq":              "Groq AI processing",
    "deepseek":          "DeepSeek AI processing",
    "openrouter":        "OpenRouter AI processing",
    "ai_generic":        "AI processing",
    "ai_rate_limit":     "AI rate-limit backoff",
    "ai_all_exhausted":  "AI providers cooling down",
    "ai_error":          "AI error retry",
    "email_send":        "Gmail SMTP cooldown",
    "email_error":       "Email error backoff",
    "imap_check":        "Gmail IMAP scanning",
    "between_leads":     "General lead pacing",
    "between_companies": "General company pacing",
}


def rand(min_s: float, max_s: float) -> float:
    """Returns a random float between min_s and max_s, rounded to 4dp."""
    return round(random.uniform(min_s, max_s), 4)


def wait(category: str, verbose: bool = True) -> float:
    """
    Sleeps for a random duration based on category.
    Returns the actual sleep duration.

    Args:
        category: key from LIMITS table
        verbose:  if True, prints the sleep duration

    Example:
        wait("ddg_search")      → sleeps ~3.2s, returns 3.2847
        wait("email_send")      → sleeps ~14.3s, returns 14.3291
    """
    if category not in LIMITS:
        # Unknown category — safe default
        duration = rand(1.0, 3.0)
        label    = category
    else:
        min_s, max_s = LIMITS[category]
        duration = rand(min_s, max_s)
        label    = CATEGORY_LABELS.get(category, category)

    if verbose:
        print(f"  ⏱  [{label}] waiting {duration}s...")

    time.sleep(duration)
    return duration


def wait_between(min_s: float, max_s: float, label: str = "") -> float:
    """
    Custom range wait — for one-off cases not in the table.
    Example: wait_between(5, 15, "custom scrape")
    """
    duration = rand(min_s, max_s)
    if label:
        pass  # silent by default
    time.sleep(duration)
    return duration


def get_delay(category: str) -> float:
    """
    Returns the delay WITHOUT sleeping — useful for logging before sleep.
    Example:
        d = get_delay("email_send")
        print(f"Sending in {d}s...")
        time.sleep(d)
    """
    if category not in LIMITS:
        return rand(1.0, 3.0)
    min_s, max_s = LIMITS[category]
    return rand(min_s, max_s)