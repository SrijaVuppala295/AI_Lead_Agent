"""
email_sender.py — Gmail SMTP Sender + IMAP Reply Checker
==========================================================
Sends emails via Gmail SMTP.
Checks replies via Gmail IMAP.
Maintains thread via Message-ID / References headers.

SETUP:
  Gmail → Settings → Security → App Passwords
  Generate password for "Mail" → paste in .env as GMAIL_APP_PASSWORD
"""

import smtplib
import imaplib
import asyncio
from utils.rate_limiter import wait, get_delay
import email as email_lib
import os
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from utils.database import (
    get_emails_by_status,
    update_email_status,
    get_emails_for_lead,
    get_campaign_stats
)
from agents.excel_writer import write_email_sent_to_row, write_reply_to_row


GMAIL_ADDRESS  = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
IMAP_HOST      = "imap.gmail.com"
IMAP_PORT      = 993

# Rate limiting handled by rate_limiter.py
# email_send: 8–20s random, email_error: 15–35s random


# ═══════════════════════════════════════════════════════════════════════════
# SEND EMAIL
# ═══════════════════════════════════════════════════════════════════════════

def send_email(email_row, is_followup=False):
    """
    Sends a single email via Gmail SMTP.
    Handles threading for followups via References header.
    
    NOTE: This function uses blocking calls (SMTP) but is called from async context.
    The blocking delay is done via asyncio.sleep() in the calling code (discord_bot.py)

    email_row columns:
      0:id 1:lead_id 2:company 3:contact_name 4:contact_email
      5:subject 6:body 7:type 8:status 9:message_id 10:thread_id
      11:sent_at 12:replied_at 13:created_at
    """
    email_id     = email_row[0]
    contact_name = email_row[3]
    to_email     = email_row[4]
    subject      = email_row[5]
    body         = email_row[6]
    email_type   = email_row[7]
    thread_id    = email_row[10]  # original message_id for followups

    if not to_email or "@" not in to_email:
        return False, "Invalid email address"

    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{GMAIL_ADDRESS}"
        msg["To"]      = to_email
        msg["Subject"] = subject

        # Threading headers for followups
        if is_followup and thread_id:
            msg["References"] = thread_id
            msg["In-Reply-To"] = thread_id

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            server.send_message(msg)

        # Save Message-ID for threading
        message_id = msg.get("Message-ID", f"<{email_id}@strikin>")
        sent_at    = datetime.now(timezone.utc).isoformat()

        update_email_status(email_id, "sent",
                            message_id=message_id,
                            sent_at=sent_at)

        # ── Write to Excel immediately ───────────────────────────────
        write_email_sent_to_row(email_row[2], email_type)  # company_name, type

        # NOTE: Delay is now handled in discord_bot.py using asyncio.sleep()
        # to avoid blocking the Discord bot's event loop

        return True, message_id

    except smtplib.SMTPAuthenticationError:
        wait("email_error")  # 15–35s before retry
        return False, "Gmail auth failed — check GMAIL_APP_PASSWORD in .env"
    except smtplib.SMTPRecipientsRefused:
        wait("email_error")
        return False, f"Email rejected: {to_email}"
    except Exception as e:
        wait("email_error")
        return False, str(e)


# ═══════════════════════════════════════════════════════════════════════════
# CHECK REPLIES VIA IMAP
# ═══════════════════════════════════════════════════════════════════════════

def check_replies():
    """
    Connects to Gmail IMAP and scans inbox for replies to sent emails.
    Updates DB status to 'replied' when reply found.
    Returns list of replied companies.
    """
    replied = []

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        mail.select("INBOX")

        # Get all sent emails that haven't replied yet
        sent_emails = get_emails_by_status("sent")

        # Filter: only look for emails from the leads we actually sent to
        unique_leads = list({s[4] for s in sent_emails if s[4]})
        
        if not unique_leads:
            print("  ℹ️  No pending leads to check replies for.")
            mail.logout()
            return []

        print(f"  🔍 Checking for replies from {len(unique_leads)} leads...")
        
        msg_nums_to_check = set()
        
        # Target scan: Search only for emails from these specific leads
        # We use Gmail-specific fast search (X-GM-RAW) if possible, chunked to avoid limits
        for i in range(0, len(unique_leads), 20):
            chunk = unique_leads[i:i+20]
            try:
                # Gmail efficient search
                search_query = f"from:({ ' | '.join(chunk) })"
                _, data = mail.search(None, 'X-GM-RAW', search_query)
                if data[0]:
                    msg_nums_to_check.update(data[0].split())
            except Exception:
                # Fallback to standard IMAP if X-GM-RAW fails (search last 7 days)
                from datetime import date, timedelta
                search_date = (date.today() - timedelta(days=7)).strftime("%d-%b-%Y")
                _, data = mail.search(None, f"(SINCE {search_date})")
                if data[0]:
                    # We have to be more broad here but we'll still only match against sent_emails
                    msg_nums_to_check.update(data[0].split())
                break # Only do one broad search if chunked targeting fails

        if not msg_nums_to_check:
            mail.logout()
            return []

        print(f"  📥 Found {len(msg_nums_to_check)} candidate emails from leads. Verifying reply headers...")

        for num in sorted(list(msg_nums_to_check), reverse=True):
            try:
                # Fetch only headers to save bandwidth and time
                _, msg_data = mail.fetch(num, "(BODY[HEADER.FIELDS (REFERENCES IN-REPLY-TO FROM)])")
                raw_headers = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw_headers)

                # Check References and In-Reply-To headers
                references  = msg.get("References", "")
                in_reply_to = msg.get("In-Reply-To", "")
                from_header = msg.get("From", "")

                # Match against our sent emails
                for sent in sent_emails:
                    sent_message_id = sent[9]  # message_id column
                    if not sent_message_id:
                        continue

                    if (sent_message_id in references or
                        sent_message_id in in_reply_to):

                        # Found a reply!
                        replied_at = datetime.now(timezone.utc).isoformat()
                        update_email_status(sent[0], "replied",
                                            replied_at=replied_at)
                        write_reply_to_row(sent[2])  # company_name column
                        replied.append({
                            "email_id":     sent[0],
                            "company_name": sent[2],
                            "contact_name": sent[3],
                            "from":         from_header,
                        })

            except Exception:
                continue

        mail.logout()
        wait("imap_check")  # 2–5s after IMAP scan

    except imaplib.IMAP4.error as e:
        print(f"  ❌ IMAP error: {e}")
        wait("imap_check")
    except Exception as e:
        print(f"  ❌ Reply check error: {e}")
        wait("imap_check")

    return replied


# ═══════════════════════════════════════════════════════════════════════════
# CAMPAIGN STATUS
# ═══════════════════════════════════════════════════════════════════════════

def get_status_report():
    """Returns formatted campaign status string."""
    stats = get_campaign_stats()
    return (
        f"📊 **Email Campaign Status**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✉️  Total Emails:    {stats['total']}\n"
        f"🤖 Generated:       {stats['generated']}\n"
        f"📤 Sent:            {stats['sent']}\n"
        f"💬 Replied:         {stats['replied']}\n"
        f"⏳ Pending:         {stats['pending']}\n"
    )