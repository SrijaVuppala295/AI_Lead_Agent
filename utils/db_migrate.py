"""
db_migrate.py — Safe DB Migration
===================================
Adds missing columns to existing leads.db without losing data.
Run this ONCE if you get "no such column" errors.

Usage: python db_migrate.py
"""

import sqlite3
import os

DB_PATH = "leads.db"

NEW_COLUMNS = [
    ("contact_name",    "TEXT"),
    ("contact_title",   "TEXT"),
    ("company_website", "TEXT"),
    ("linkedin_url",    "TEXT"),
    ("contact_email",   "TEXT"),
    ("email_status",    "TEXT DEFAULT 'no_email'"),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print("  ⚠️  leads.db not found — run python main.py option 1 first")
        return

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(raw_leads)")
    existing = {row[1] for row in cursor.fetchall()}
    print(f"  Existing columns: {sorted(existing)}")

    added = 0
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            try:
                cursor.execute(f"ALTER TABLE raw_leads ADD COLUMN {col_name} {col_type}")
                print(f"  ✅ Added column: {col_name}")
                added += 1
            except Exception as e:
                print(f"  ⚠️  {col_name}: {e}")
        else:
            print(f"  ✓  Already exists: {col_name}")

    # Create emails table if missing
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id       INTEGER,
            company_name  TEXT,
            contact_name  TEXT,
            contact_email TEXT,
            subject       TEXT,
            body          TEXT,
            email_type    TEXT,
            status        TEXT DEFAULT 'generated',
            message_id    TEXT,
            thread_id     TEXT,
            sent_at       TIMESTAMP,
            replied_at    TIMESTAMP,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES raw_leads(id)
        )
    """)
    print("  ✅ emails table ready")

    conn.commit()
    conn.close()

    print(f"\n  {'✅ Migration complete' if added > 0 else '✅ Already up to date'}")
    print(f"  Added {added} columns")
    print(f"  → Run python main.py normally now")

if __name__ == "__main__":
    print("\n🔧 DB MIGRATION")
    print("="*40)
    migrate()
    print("="*40 + "\n")