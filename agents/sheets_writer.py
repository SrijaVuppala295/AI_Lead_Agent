"""
sheets_writer.py — Google Sheets Output
==========================================
ONE sheet: "Leads"
One row per lead. Each email has its own Subject + Body + Status columns.

COLUMN GROUPS:
  Lead Info (navy)    : Company, Contact, Title, LinkedIn, Website, Email, Source, Signal, Score, Date
  Original (blue)     : Subject | Body | Status
  Followup 1 (purple) : Subject | Body | Status
  Followup 2 (purple) : Subject | Body | Status
  Followup 3 (purple) : Subject | Body | Status
"""

import re
import gspread
from google.oauth2.service_account import Credentials
import os
from utils.database import get_all_leads, get_emails_by_status

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_sheet_client():
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


def _rgb(r, g, b):
    return {"red": r/255, "green": g/255, "blue": b/255}

# Header colors
HDR_LEAD   = _rgb(31,  56, 100)   # navy
HDR_ORIG   = _rgb(21, 101, 192)   # blue
HDR_FU     = _rgb(106, 27, 154)   # purple
WHITE      = _rgb(255, 255, 255)

# Row / cell colors
HOT        = _rgb(255, 224, 224)
WARM       = _rgb(255, 253, 231)
EMAIL_ROW  = _rgb(232, 245, 233)
ALT        = _rgb(245, 245, 245)
ORIG_CELL  = _rgb(227, 242, 253)
FU_CELL    = _rgb(243, 229, 245)


def _clean_email(email):
    if not email or "@" not in email:
        return email
    m = re.match(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,6}", email)
    return m.group(0) if m else email


def _email_status(em):
    if em is None:
        return "not generated"
    s = em[8] or "generated"
    if s == "replied":   return "replied ✅"
    if s == "sent":      return "sent ✉️"
    if s == "generated": return "generated ✅"
    return s


def _get_or_create_sheet(spreadsheet, title, rows=200, cols=25):
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
        return ws
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title, rows=rows, cols=cols)


def _delete_other_sheets(spreadsheet, keep):
    for ws in spreadsheet.worksheets():
        if ws.title not in keep:
            try:
                spreadsheet.del_worksheet(ws)
            except Exception:
                pass


# ── Column definitions ─────────────────────────────────────────────────────
# (header, group, width_px)
COLS = [
    ("Company Name",         "lead",  180),
    ("Contact Name",         "lead",  150),
    ("Title",                "lead",  160),
    ("LinkedIn URL",         "lead",  240),
    ("Company Website",      "lead",  200),
    ("Contact Email",        "lead",  210),
    ("Signal Source",        "lead",  130),
    ("Signal Summary",       "lead",  320),
    ("Intent Score",         "lead",  100),
    ("Date Found",           "lead",  130),
    # Original
    ("Original Subject",     "orig",  240),
    ("Original Body",        "orig",  400),
    ("Original Status",      "orig",  140),
    # Followup 1
    ("Followup 1 Subject",   "fu",    240),
    ("Followup 1 Body",      "fu",    400),
    ("Followup 1 Status",    "fu",    140),
    # Followup 2
    ("Followup 2 Subject",   "fu",    240),
    ("Followup 2 Body",      "fu",    400),
    ("Followup 2 Status",    "fu",    140),
    # Followup 3
    ("Followup 3 Subject",   "fu",    240),
    ("Followup 3 Body",      "fu",    400),
    ("Followup 3 Status",    "fu",    140),
]

HDR_COLOR_MAP = {"lead": HDR_LEAD, "orig": HDR_ORIG, "fu": HDR_FU}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def push_to_sheets():
    try:
        spreadsheet = get_sheet_client()
    except Exception as e:
        print(f"  ❌ Google Sheets auth failed: {e}")
        return False

    leads  = get_all_leads()
    emails = get_emails_by_status()

    if not leads:
        print("  ⚠️  No leads in DB")
        return False

    # Index: lead_id → {email_type: row}
    email_idx = {}
    for em in emails:
        lid, etype = em[1], em[7] or ""
        email_idx.setdefault(lid, {})[etype] = em

    ws = _get_or_create_sheet(spreadsheet, "Leads", rows=len(leads)+10, cols=len(COLS)+2)
    _delete_other_sheets(spreadsheet, ["Leads"])
    sid = ws._properties["sheetId"]

    # ── Build rows ─────────────────────────────────────────────────────────
    all_rows = [[c[0] for c in COLS]]   # header

    for lead in leads:
        lead_id         = lead[0]
        company_name    = lead[1]  or ""
        signal_title    = lead[2]  or ""
        urgency_score   = lead[4]  or 0
        source_name     = lead[7]  or ""
        date_found      = str(lead[8] or "")
        contact_name    = lead[9]  if len(lead) > 9  else "TBD"
        contact_title   = lead[10] if len(lead) > 10 else "TBD"
        company_website = lead[11] if len(lead) > 11 else "TBD"
        linkedin_url    = lead[12] if len(lead) > 12 else "TBD"
        contact_email   = _clean_email(lead[13]) if len(lead) > 13 and lead[13] else "TBD"

        le   = email_idx.get(lead_id, {})
        orig = le.get("original")
        fu1  = le.get("followup_1")
        fu2  = le.get("followup_2")
        fu3  = le.get("followup_3")

        all_rows.append([
            company_name,
            contact_name    or "TBD",
            contact_title   or "TBD",
            linkedin_url    or "TBD",
            company_website or "TBD",
            contact_email,
            source_name,
            signal_title,
            urgency_score,
            date_found,
            # Original
            orig[5] if orig else "",
            orig[6] if orig else "",
            _email_status(orig),
            # Followup 1
            fu1[5]  if fu1  else "",
            fu1[6]  if fu1  else "",
            _email_status(fu1),
            # Followup 2
            fu2[5]  if fu2  else "",
            fu2[6]  if fu2  else "",
            _email_status(fu2),
            # Followup 3
            fu3[5]  if fu3  else "",
            fu3[6]  if fu3  else "",
            _email_status(fu3),
        ])

    ws.update(values=all_rows, range_name="A1")

    # ── Formatting ─────────────────────────────────────────────────────────
    requests = []
    num_cols = len(COLS)
    num_rows = len(all_rows)

    # 1. Header — color per group
    for col_idx, (header, group, width) in enumerate(COLS):
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": col_idx, "endColumnIndex": col_idx+1
                },
                "cell": {"userEnteredFormat": {
                    "backgroundColor": HDR_COLOR_MAP[group],
                    "textFormat": {
                        "foregroundColor": WHITE,
                        "bold": True, "fontSize": 11, "fontFamily": "Arial"
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)"
            }
        })

    # 2. Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"
        }
    })

    # 3. Column widths
    for col_idx, (header, group, width) in enumerate(COLS):
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": col_idx, "endIndex": col_idx+1},
                "properties": {"pixelSize": width},
                "fields": "pixelSize"
            }
        })

    # 4. Per-row colors
    for row_idx, lead in enumerate(leads, 1):
        lead_id    = lead[0]
        score      = lead[4] or 0
        le         = email_idx.get(lead_id, {})
        has_emails = bool(le)

        row_bg = (EMAIL_ROW if has_emails
                  else HOT   if score >= 7
                  else WARM  if score >= 5
                  else ALT   if row_idx % 2 == 0
                  else WHITE)

        # Lead info columns (0-9) — row color
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": row_idx, "endRowIndex": row_idx+1,
                          "startColumnIndex": 0, "endColumnIndex": 10},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": row_bg,
                    "textFormat": {"fontSize": 10, "fontFamily": "Arial"},
                    "verticalAlignment": "TOP", "wrapStrategy": "WRAP"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"
            }
        })

        # Original columns (10-12) — light blue
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": row_idx, "endRowIndex": row_idx+1,
                          "startColumnIndex": 10, "endColumnIndex": 13},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": ORIG_CELL,
                    "textFormat": {"fontSize": 9, "fontFamily": "Arial"},
                    "verticalAlignment": "TOP", "wrapStrategy": "WRAP"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"
            }
        })

        # Followup columns (13-21) — light purple
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sid,
                          "startRowIndex": row_idx, "endRowIndex": row_idx+1,
                          "startColumnIndex": 13, "endColumnIndex": 22},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": FU_CELL,
                    "textFormat": {"fontSize": 9, "fontFamily": "Arial"},
                    "verticalAlignment": "TOP", "wrapStrategy": "WRAP"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"
            }
        })

    # 5. Row heights
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 40}, "fields": "pixelSize"
        }
    })
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": 1, "endIndex": num_rows},
            "properties": {"pixelSize": 130}, "fields": "pixelSize"
        }
    })

    spreadsheet.batch_update({"requests": requests})

    print(f"  ✅ Google Sheets updated → 'Leads' sheet")
    print(f"     📋 {len(leads)} leads | {len(emails)} emails")
    print(f"     🔗 https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}")
    return True