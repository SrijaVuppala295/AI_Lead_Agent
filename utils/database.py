"""
database.py — SQLite Database Layer
=====================================
Tables:
  processed_signals — URL deduplication
  raw_leads         — all leads with contact info
  emails            — email campaign tracking
  agent_metadata    — last run timestamp
"""

import sqlite3
from datetime import datetime, timezone, timedelta
import os

DB_PATH = "leads.db"


def init_db():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── Signals dedup table ───────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            url          TEXT UNIQUE,
            source       TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Leads table ───────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name    TEXT UNIQUE,
            signal_title    TEXT,
            why_relevant    TEXT,
            urgency_score   INTEGER,
            signal_category TEXT,
            source_url      TEXT,
            source_name     TEXT,
            date_found      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            contact_name    TEXT,
            contact_title   TEXT,
            company_website TEXT,
            linkedin_url    TEXT,
            contact_email   TEXT,
            email_status    TEXT DEFAULT 'no_email'
        )
    """)

    # ── Email campaign table ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id      INTEGER,
            company_name TEXT,
            contact_name TEXT,
            contact_email TEXT,
            subject      TEXT,
            body         TEXT,
            email_type   TEXT,  -- original / followup_1 / followup_2 / followup_3
            status       TEXT DEFAULT 'generated',  -- generated/sent/replied/pending
            message_id   TEXT,  -- Gmail Message-ID for threading
            thread_id    TEXT,  -- original message_id for all followups
            sent_at      TIMESTAMP,
            replied_at   TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES raw_leads(id)
        )
    """)

    # ── Metadata table ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_metadata (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Set initial timestamp to 14 days ago on first run
    cursor.execute("SELECT value FROM agent_metadata WHERE key='last_run_timestamp'")
    if not cursor.fetchone():
        two_weeks_ago = (
            datetime.now(timezone.utc) - timedelta(days=14)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO agent_metadata (key, value) VALUES ('last_run_timestamp', ?)",
            (two_weeks_ago,)
        )

    conn.commit()
    conn.close()
    print("✅ Database initialized")


# ── Signal functions ──────────────────────────────────────────────────────

def is_already_processed(url):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_signals WHERE url=?", (url,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_as_processed(url, source):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO processed_signals (url, source) VALUES (?, ?)",
            (url, source)
        )
        conn.commit()
    finally:
        conn.close()

def get_processed_count():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM processed_signals")
    count = cursor.fetchone()[0]
    conn.close()
    return count


# ── Timestamp functions ───────────────────────────────────────────────────

def get_last_run_timestamp():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM agent_metadata WHERE key='last_run_timestamp'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_last_run_timestamp():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO agent_metadata (key, value)
        VALUES ('last_run_timestamp', datetime('now'))
    """)
    conn.commit()
    conn.close()


# ── Lead functions ────────────────────────────────────────────────────────

def save_lead(lead):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO raw_leads
            (company_name, signal_title, why_relevant, urgency_score,
             signal_category, source_url, source_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            lead.get("company_name"),
            lead.get("signal_title"),
            lead.get("why_relevant"),
            lead.get("urgency_score"),
            lead.get("signal_category"),
            lead.get("source_url"),
            lead.get("source_name"),
        ))
        conn.commit()
    finally:
        conn.close()

def get_all_leads():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, company_name, signal_title, why_relevant,
               urgency_score, signal_category, source_url, source_name,
               date_found,
               COALESCE(contact_name, 'TBD')    as contact_name,
               COALESCE(contact_title, 'TBD')   as contact_title,
               COALESCE(company_website, 'TBD') as company_website,
               COALESCE(linkedin_url, 'TBD')    as linkedin_url,
               COALESCE(contact_email, '')       as contact_email,
               COALESCE(email_status, 'no_email') as email_status
        FROM raw_leads
        ORDER BY urgency_score DESC
    """)
    leads = cursor.fetchall()
    conn.close()
    return leads

def get_lead_count():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_leads")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def update_lead_contact(lead_id, contact):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE raw_leads
            SET contact_name    = ?,
                contact_title   = ?,
                company_website = ?,
                linkedin_url    = ?
            WHERE id = ?
        """, (
            contact.get("contact_name"),
            contact.get("contact_title"),
            contact.get("company_website"),
            contact.get("linkedin_url"),
            lead_id
        ))
        conn.commit()
    finally:
        conn.close()

def update_lead_email(lead_id, email):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE raw_leads
            SET contact_email = ?,
                email_status  = 'discovered'
            WHERE id = ?
        """, (email, lead_id))
        conn.commit()
    finally:
        conn.close()


# ── Email campaign functions ──────────────────────────────────────────────

def save_email(lead_id, company_name, contact_name, contact_email,
               subject, body, email_type, thread_id=None):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO emails
            (lead_id, company_name, contact_name, contact_email,
             subject, body, email_type, status, thread_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'generated', ?)
        """, (lead_id, company_name, contact_name, contact_email,
              subject, body, email_type, thread_id))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_emails_by_status(status=None):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM emails WHERE status=? ORDER BY lead_id ASC, created_at ASC",
            (status,)
        )
    else:
        cursor.execute("SELECT * FROM emails ORDER BY lead_id ASC, created_at ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_emails_for_lead(lead_id):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM emails WHERE lead_id=? ORDER BY email_type",
        (lead_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_email_by_company_and_type(company_name, email_type):
    """Get email ID by company name and email type."""
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM emails WHERE company_name=? AND email_type=?",
        (company_name, email_type)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_email_status(email_id, status, message_id=None, sent_at=None, replied_at=None):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        if status == "sent":
            cursor.execute("""
                UPDATE emails SET status=?, message_id=?, sent_at=?
                WHERE id=?
            """, (status, message_id, sent_at, email_id))
        elif status == "replied":
            cursor.execute("""
                UPDATE emails SET status=?, replied_at=?
                WHERE id=?
            """, (status, replied_at, email_id))
        else:
            cursor.execute(
                "UPDATE emails SET status=? WHERE id=?",
                (status, email_id)
            )
        conn.commit()
    finally:
        conn.close()

def update_contact_email(lead_id, new_email):
    """Update contact email for a lead and all related emails."""
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Update in leads table
        cursor.execute(
            "UPDATE raw_leads SET contact_email=? WHERE id=?",
            (new_email, lead_id)
        )
        # Update in emails table
        cursor.execute(
            "UPDATE emails SET contact_email=? WHERE lead_id=?",
            (new_email, lead_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error updating email: {e}")
        return False
    finally:
        conn.close()

def get_campaign_stats():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='generated' THEN 1 ELSE 0 END) as generated,
            SUM(CASE WHEN status='sent'      THEN 1 ELSE 0 END) as sent,
            SUM(CASE WHEN status='replied'   THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN status='pending'   THEN 1 ELSE 0 END) as pending
        FROM emails
    """)
    row = cursor.fetchone()
    conn.close()
    return {
        "total":     row[0] or 0,
        "generated": row[1] or 0,
        "sent":      row[2] or 0,
        "replied":   row[3] or 0,
        "pending":   row[4] or 0,
    }

def get_leads_with_email():
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, company_name, contact_name, contact_title,
               contact_email, urgency_score, company_website,
               signal_title, why_relevant
        FROM raw_leads
        WHERE contact_email IS NOT NULL
          AND contact_email != ''
          AND contact_email != 'Not found'
        ORDER BY urgency_score DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_leads_needing_email_gen():
    """Leads with email but no generated emails yet."""
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.company_name, r.contact_name, r.contact_title,
               r.contact_email, r.urgency_score, r.company_website,
               r.signal_title, r.why_relevant
        FROM raw_leads r
        LEFT JOIN emails e ON r.id = e.lead_id AND e.email_type = 'original'
        WHERE r.contact_email IS NOT NULL
          AND r.contact_email != ''
          AND r.contact_email != 'Not found'
          AND e.id IS NULL
        ORDER BY r.urgency_score DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows