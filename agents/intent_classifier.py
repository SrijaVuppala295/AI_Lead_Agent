"""
intent_classifier.py — Intent Classification Engine
=====================================================
Uses Groq (Llama 3.3 70B) to classify RSS signals as buying signals.

WHY GROQ OVER GEMINI:
  - Free tier — no quota issues
  - Faster than Gemini (sub-second responses)
  - Llama 3.3 70B — excellent at JSON classification tasks

PIPELINE:
  Step 1 → Pre-filter obvious non-signals (instant, no API call)
  Step 2 → Batch 10 signals per API call (10x fewer calls)
  Step 3 → Parse + deduplicate companies
  Step 4 → Save qualified leads (score 5+) to DB
  Step 5 → Return hot leads (score 7+) for Discord alerts

FIXES FROM DAY 2:
  - Duplicate companies tracked — same company never printed/saved twice
  - Stricter prompt — resorts/hotels/generic tech filtered out
  - India companies prioritized — non-India capped at score 6
"""

from groq import Groq
import os
import json
import time
from utils.database import save_lead
from agents.excel_writer import write_lead_row


# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"


# ═══════════════════════════════════════════════════════════════════════════
# PRE-FILTER — Instant keyword check, no API call needed
# Removes ~30-40% of signals before sending to Groq
# ═══════════════════════════════════════════════════════════════════════════

DISCARD_KEYWORDS = [
    "mortgage rate", "interest rate", "home loan rate",
    "property tax", "rental yield", "bond yield",
    "insurance premium", "best reverse mortgage",
    "divorce", "celebrity", "recipe", "cricket",
    "women's day", "bold care", "hotel manager",
    "rural investment", "weather", "stock market",
    "do-not-call", "fsbo", "linkedin study",
    "open letter", "opinion", "back to basics",
    "court sides", "patchwork", "energy resilience",
    "data sovereignty", "aviation noise", "federal government",
    "china turns", "uk mortgage", "canada mortgage",
    "bond yields", "middle east", "panic-buy",
    "tamara", "hospitality group", "hotel chain",
    "resort", "spa", "restaurant chain", "food delivery",
    "royal orchid", "orchid hotel", "hotel expansion",
    "360 one asset", "asset management", "mutual fund",
    "wealth management", "hedge fund", "investment fund"
]

def is_obviously_irrelevant(signal):
    """
    Fast pre-filter — returns True if signal is clearly not a buying signal.
    No API call needed — pure string matching.
    """
    text = (signal.get("title", "") + " " + signal.get("summary", "")).lower()
    return any(kw in text for kw in DISCARD_KEYWORDS)


# ═══════════════════════════════════════════════════════════════════════════
# BATCH PROMPT — Strict rules to reduce noise
# ═══════════════════════════════════════════════════════════════════════════

def build_batch_prompt(batch):
    """
    Builds strict classification prompt for a batch of signals.

    KEY PROMPT IMPROVEMENTS FROM DAY 2:
      - Explicitly rejects resorts, hotels, hospitality
      - India companies score higher (7-10)
      - Non-India companies capped at 6
      - Requires specific company name — no company = score 0
      - Generic tech companies without PropTech focus = rejected
    """
    signals_text = ""
    for i, signal in enumerate(batch):
        signals_text += f"""
SIGNAL {i+1}:
Title: {signal['title']}
Summary: {signal['summary'][:300]}
Source: {signal['source']}
---"""

    return f"""You are a sales intelligence AI for Strikin — a PropTech software company
that sells digital platform tools to real estate companies in India.

Analyze each signal. Determine if it is a BUYING SIGNAL for Strikin.

A BUYING SIGNAL means a REAL ESTATE or PROPTECH company that is:
- Raising funds specifically for digital platform or tech upgrade
- Launching a new real estate digital product or app
- Hiring tech team, CTO, or software developers for real estate
- Adopting CRM, ERP, or PropTech software
- Announcing digital transformation of real estate operations
- Expanding real estate business into new markets

STRICT REJECTION RULES — score 0 for any of these:
- Resorts, hotels, hospitality companies → NOT real estate tech buyers
- Generic tech companies not focused on real estate → REJECT
- No specific company name mentioned → score 0
- If article mentions multiple companies → pick ONLY the single most relevant one
- NEVER combine multiple company names with commas (e.g. never "Compass, Redfin")
- One signal = one company name only
- Generic terms like "Japan PropTech", "Asia PropTech", "India PropTech" are NOT company names → score 0
- Single letters or numbers like "7R", "5i", "360" without full context → score 0
- Generic words like "Agora", "Compass", "Hines", "NAS" without clear PropTech buying signal → score 0
- Conglomerates like "Al-Futtaim" that are not specifically a real estate tech company → max score 4
- Real estate investment companies, REITs, asset managers → max score 5 (not PropTech buyers)
- Only India-based PropTech startups raising funds / launching platform → can score 7-10
- General market reports, price analysis, mortgage rates → REJECT
- Government policy announcements → REJECT
- Opinion articles, thought leadership → REJECT
- Companies not in real estate or PropTech industry → REJECT

SCORING RULES:
- India-based real estate/PropTech company → can score 7-10
- Non-India company (US/Europe/Middle East) → maximum score 6
- Strong India signal (funding, launch, hiring) → score 8-10
- Weak or indirect signal → score 4-5
- Not a signal → score 0

CATEGORIES: FUNDING / LAUNCH / HIRING / CRM_ADOPTION / DIGITAL_TRANSFORM / EXPANSION / OTHER

{signals_text}

Respond ONLY with a valid JSON array — no markdown, no extra text, no explanation:
[
  {{
    "signal_number": 1,
    "is_buying_signal": true or false,
    "company_name": "exact company name or null",
    "signal_category": "CATEGORY",
    "what_they_are_doing": "one sentence describing what the company is doing",
    "why_relevant": "one sentence why Strikin should contact them specifically",
    "urgency_score": 0-10
  }}
]
Respond with exactly {len(batch)} objects in the array."""


# ═══════════════════════════════════════════════════════════════════════════
# BATCH CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

def classify_batch(batch):
    """
    Sends one batch to Groq, returns list of classification results.
    Returns empty list on any failure.
    """
    prompt = build_batch_prompt(batch)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        text = response.choices[0].message.content.strip()

        # Clean markdown fences if present
        text = text.replace("```json", "").replace("```", "").strip()

        # Parse JSON array
        results = json.loads(text)
        return results if isinstance(results, list) else []

    except json.JSONDecodeError:
        # Try extracting JSON array from messy response
        try:
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass
        return []

    except Exception as e:
        error_msg = str(e).lower()
        if "429" in error_msg or "rate" in error_msg:
            print(f"  ⏳ Rate limit — waiting 15 seconds...")
            time.sleep(15)
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                text = response.choices[0].message.content.strip()
                text = text.replace("```json", "").replace("```", "").strip()
                return json.loads(text)
            except Exception:
                return []
        return []


# ═══════════════════════════════════════════════════════════════════════════
# MASTER CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

def classify_all_signals(signals):
    """
    Main function called from main.py.

    PIPELINE:
      1. Pre-filter obvious non-signals
      2. Batch into groups of 10
      3. Classify each batch with Groq
      4. Deduplicate by company name
      5. Save qualified leads to DB
      6. Return results + stats
    """
    print("\n🧠 INTENT CLASSIFICATION STARTING")
    print("="*55)

    # ── Step 1: Pre-filter ────────────────────────────────────────────────
    filtered = [s for s in signals if not is_obviously_irrelevant(s)]
    pre_filtered_count = len(signals) - len(filtered)

    print(f"  Total signals:     {len(signals)}")
    print(f"  Pre-filtered:      {pre_filtered_count} (obvious non-signals)")
    print(f"  Sending to Groq:   {len(filtered)}")

    # ── Step 2: Batch into groups of 10 ──────────────────────────────────
    BATCH_SIZE = 10
    batches = [
        filtered[i:i+BATCH_SIZE]
        for i in range(0, len(filtered), BATCH_SIZE)
    ]

    print(f"  API calls needed:  {len(batches)}")
    print(f"  Estimated time:    ~{len(batches) * 3} seconds")
    print("="*55)

    all_leads       = []
    hot_leads       = []
    discarded       = pre_filtered_count
    errors          = 0
    seen_companies  = set()  # FIX: track seen companies — no duplicates

    # ── Step 3: Process each batch ────────────────────────────────────────
    for batch_num, batch in enumerate(batches, 1):
        print(f"  ⏳ Batch {batch_num}/{len(batches)}...")

        results = classify_batch(batch)

        if not results:
            errors += len(batch)
            time.sleep(2)
            continue

        for result, signal in zip(results, batch):

            # Not a buying signal
            if not result.get("is_buying_signal"):
                discarded += 1
                continue

            score   = result.get("urgency_score", 0)
            company = result.get("company_name")

            # Score too low or no company name
            if score < 5 or not company:
                discarded += 1
                continue

            # FIX: Skip duplicate companies
            # Same company can appear in multiple batches/sources
            company_key = company.lower().strip()
            if company_key in seen_companies:
                discarded += 1
                continue
            seen_companies.add(company_key)

            # Build lead
            lead = {
                "company_name":    company,
                "signal_title":    signal["title"],
                "why_relevant":    result.get("why_relevant"),
                "urgency_score":   score,
                "signal_category": result.get("signal_category"),
                "source_url":      signal["url"],
                "source_name":     signal["source"],
            }

            # Save to DB
            save_lead(lead)

            # ── Write to Excel immediately ────────────────────────────────
            write_lead_row({
                "company_name":  company,
                "signal_title":  signal["title"],
                "urgency_score": score,
                "source_name":   signal["source"],
                "date_found":    lead.get("date_found", ""),
            })

            all_leads.append(lead)

            # Hot lead
            if score >= 7:
                hot_leads.append(lead)
                print(f"\n  🔥 HOT [{score}/10] — {company}")
                print(f"     {result.get('why_relevant')}")
            else:
                print(f"  ✅ WARM [{score}/10] — {company}")

        time.sleep(2)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n  ──────────────────────────────────────────")
    print(f"   🧠  AI CLASSIFICATION COMPLETE")
    print(f"   ✅  {len(all_leads) - len(hot_leads)} Warm leads qualified")
    print(f"   🔥  {len(hot_leads)} Hot leads identified")
    print(f"   🗑️   {discarded} irrelavant signals discarded")
    print("  ──────────────────────────────────────────")

    return {
        "all_leads": all_leads,
        "hot_leads": hot_leads,
        "stats": {
            "total_signals": len(signals),
            "total_leads":   len(all_leads),
            "hot_leads":     len(hot_leads),
            "discarded":     discarded,
            "errors":        errors
        }
    }