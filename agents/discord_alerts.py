"""
discord_alerts.py — Discord Hot Lead Alerts
=============================================
Sends instant Discord notifications for hot leads (score 7+).

WHY DISCORD:
  - Already have a bot set up
  - Instant notification — no polling needed
  - Rich embed format — looks professional
  - Free forever

SETUP NEEDED IN .env:
  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

HOW TO GET WEBHOOK URL:
  Discord server → channel settings → Integrations → Webhooks → New Webhook
"""

import requests
import os
from datetime import datetime


def send_hot_lead_alert(lead):
    """
    Sends a Discord embed notification for a single hot lead.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    score         = lead.get("urgency_score", 0)
    company       = lead.get("company_name", "Unknown")
    category      = lead.get("signal_category", "OTHER")
    why_relevant  = lead.get("why_relevant", "")
    signal_title  = lead.get("signal_title", "")
    source_url    = lead.get("source_url", "")
    contact_name  = lead.get("contact_name", "TBD")
    contact_title = lead.get("contact_title", "TBD")
    website       = lead.get("company_website", "TBD")

    # Score Visualization
    full_blocks = int(score)
    empty_blocks = 10 - full_blocks
    score_bar = "🟦" * full_blocks + "⬜" * empty_blocks
    
    emoji = "🔥" if score >= 8 else "✅"

    color_map = {
        "FUNDING":          0x00FF00,   # Neon Green
        "LAUNCH":           0x00BFFF,   # Deep Sky Blue
        "HIRING":           0xFFD700,   # Gold
        "CRM_ADOPTION":     0xFF4500,   # Orange Red
        "DIGITAL_TRANSFORM":0x9400D3,   # Dark Violet
        "EXPANSION":        0xFF69B4,   # Hot Pink
        "OTHER":            0x808080,   # Grey
    }
    color = color_map.get(category, 0x808080)

    embed = {
        "title": f"{emoji} {company}",
        "description": f"**Lead Priority:** {score}/10\n{score_bar}",
        "color": color,
        "fields": [
            {
                "name": "📌 Signal",
                "value": f"**{category}**: {signal_title[:150]}...",
                "inline": False
            },
            {
                "name": "👤 Target Contact",
                "value": f"**{contact_name}**\n*{contact_title}*",
                "inline": True
            },
            {
                "name": "🌐 Company Link",
                "value": f"[Visit Website]({website})" if website.startswith("http") else website,
                "inline": True
            },
            {
                "name": "💡 Why this lead?",
                "value": why_relevant or "Relevant PropTech signal detected.",
                "inline": False
            }
        ],
        "footer": {
            "text": "Strikin Sales Intelligence • automated notification"
        },
        "timestamp": datetime.now().isoformat()
    }

    if source_url:
        embed["url"] = source_url

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 204
    except Exception:
        return False


def send_run_summary(stats):
    """
    Sends a run summary to Discord after each agent run.
    Shows total signals, leads found, hot leads.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    embed = {
        "title": "📊 Lead Gen Agent — Run Complete",
        "color": 0x1F3864,
        "fields": [
            {
                "name": "Signals Collected",
                "value": str(stats.get("total_signals", 0)),
                "inline": True
            },
            {
                "name": "Leads Found",
                "value": str(stats.get("total_leads", 0)),
                "inline": True
            },
            {
                "name": "Hot Leads (7+)",
                "value": str(stats.get("hot_leads", 0)),
                "inline": True
            },
        ],
        "footer": {"text": "Strikin Lead Gen Agent"}
    }

    try:
        resp = requests.post(
            webhook_url, json={"embeds": [embed]}, timeout=10
        )
        return resp.status_code == 204
    except Exception:
        return False