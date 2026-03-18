"""
sheets_reader.py — Google Sheets Reader (Source of Truth)
===========================================================
Read leads and emails directly from Google Sheets.
Google Sheets is the main source of truth, not SQLite.
Async wrappers prevent blocking Discord event loop.
"""

import gspread
from google.oauth2.service_account import Credentials
import os
import asyncio

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_sheet_client():
    """Get authorized Google Sheets client."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        import json
        info  = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # Fallback to local file if env var not present
        creds = Credentials.from_service_account_file(
            os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"), 
            scopes=SCOPES
        )
    client = gspread.authorize(creds)
    return client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))


def get_all_leads_from_sheets():
    """
    Read all leads from Google Sheets (Leads tab).
    Returns list of tuples: (company_name, contact_name, title, linkedin, website, email, source, signal, score, date)
    """
    try:
        spreadsheet = get_sheet_client()
        ws = spreadsheet.worksheet("Leads")
        rows = ws.get_all_values()
        
        if not rows or len(rows) < 2:
            return []
        
        # Skip header row (row 0)
        leads = []
        for row in rows[1:]:
            if not row or not row[0]:  # Skip empty rows
                continue
            leads.append({
                "company_name": row[0] if len(row) > 0 else "",
                "contact_name": row[1] if len(row) > 1 else "",
                "title": row[2] if len(row) > 2 else "",
                "linkedin_url": row[3] if len(row) > 3 else "",
                "website": row[4] if len(row) > 4 else "",
                "email": row[5] if len(row) > 5 else "",  # This is the live email from Sheets
                "source": row[6] if len(row) > 6 else "",
                "signal": row[7] if len(row) > 7 else "",
                "score": row[8] if len(row) > 8 else "0",
                "date": row[9] if len(row) > 9 else "",
            })
        
        return leads
    except Exception as e:
        print(f"❌ Error reading from Google Sheets: {e}")
        return []


def get_lead_by_company(company_name):
    """Find a lead by company name (partial match)."""
    leads = get_all_leads_from_sheets()
    for lead in leads:
        if company_name.lower() in lead["company_name"].lower():
            return lead
    return None


def get_emails_from_sheets(company_name):
    """
    Read email sequences for a company from Google Sheets.
    Returns dict: {email_type: {subject, body, status}}
    """
    try:
        spreadsheet = get_sheet_client()
        ws = spreadsheet.worksheet("Leads")
        rows = ws.get_all_values()
        
        if not rows or len(rows) < 2:
            return {}
        
        # Find the row for this company
        target_row = None
        for i, row in enumerate(rows[1:], start=1):
            if row and row[0].lower() == company_name.lower():
                target_row = row
                break
        
        if not target_row:
            return {}
        
        # Extract email sequences (columns 10-21)
        # Original: 10-12, Followup1: 13-15, Followup2: 16-18, Followup3: 19-21
        emails = {}
        
        email_types = [
            ("original", 10, 11, 12),
            ("followup_1", 13, 14, 15),
            ("followup_2", 16, 17, 18),
            ("followup_3", 19, 20, 21),
        ]
        
        for email_type, subject_col, body_col, status_col in email_types:
            subject = target_row[subject_col] if len(target_row) > subject_col else ""
            body = target_row[body_col] if len(target_row) > body_col else ""
            status = target_row[status_col] if len(target_row) > status_col else ""
            
            if subject:  # Only include if subject exists
                emails[email_type] = {
                    "subject": subject,
                    "body": body,
                    "status": status,
                }
        
        return emails
    except Exception as e:
        print(f"❌ Error reading emails from Google Sheets: {e}")
        return {}


def update_email_status_sheets(company_name, email_type, status):
    """
    Update email status in Google Sheets.
    email_type: "original", "followup_1", "followup_2", "followup_3"
    status: "sent", "replied", "generated", etc.
    """
    try:
        spreadsheet = get_sheet_client()
        ws = spreadsheet.worksheet("Leads")
        rows = ws.get_all_values()
        
        if not rows or len(rows) < 2:
            return False
        
        # Find the row index for this company
        target_row_idx = None
        for i, row in enumerate(rows):
            if row and row[0].lower() == company_name.lower():
                target_row_idx = i + 1  # +1 because gspread uses 1-based indexing
                break
        
        if not target_row_idx:
            return False
        
        # Map email type to status column
        status_col_map = {
            "original": 13,      # Column M (12 + 1 for 1-based indexing)
            "followup_1": 16,    # Column P
            "followup_2": 19,    # Column S
            "followup_3": 22,    # Column V
        }
        
        if email_type not in status_col_map:
            return False
        
        col_letter = chr(64 + status_col_map[email_type])
        cell_ref = f"{col_letter}{target_row_idx}"
        
        ws.update([[status]], cell_ref)
        return True
    except Exception as e:
        print(f"❌ Error updating email status in Sheets: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# ASYNC WRAPPERS (Non-blocking for Discord event loop)
# ═══════════════════════════════════════════════════════════════════════════

async def get_all_leads_from_sheets_async():
    """Async wrapper for get_all_leads_from_sheets - runs in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_all_leads_from_sheets)


async def get_emails_from_sheets_async(company_name):
    """Async wrapper for get_emails_from_sheets - runs in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_emails_from_sheets, company_name)


async def update_email_status_sheets_async(company_name, email_type, status):
    """Async wrapper for update_email_status_sheets - runs in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, update_email_status_sheets, company_name, email_type, status)
