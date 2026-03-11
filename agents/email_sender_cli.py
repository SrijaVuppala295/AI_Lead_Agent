"""
email_sender_cli.py — Simple Email Sending Interface
=====================================================

Cleaner, command-line based interface for sending emails.
No Discord dependency.
"""

import time
from tabulate import tabulate
from utils.database import (
    get_all_leads,
    get_emails_for_lead,
    update_email_status,
    get_campaign_stats,
)
from agents.email_sender import send_email, check_replies


def display_leads():
    """Display all leads with email status."""
    leads = get_all_leads()
    if not leads:
        print("  ⚠️  No leads in database")
        return None

    table_data = []
    for i, lead in enumerate(leads, 1):
        company = lead[1]
        score = lead[4] or 0
        contact = lead[9] or "TBD"
        title = lead[10] or "TBD"
        email = lead[13] if len(lead) > 13 else ""
        email_status = lead[14] if len(lead) > 14 else "no_email"
        
        score_icon = "🔥" if score >= 7 else "✅"
        status_icon = {
            "sent": "📤",
            "replied": "💬",
            "generated": "🤖",
            "discovered": "📧",
            "no_email": "❌",
        }.get(email_status, "❓")
        
        table_data.append([
            i,
            f"{score_icon} {company}",
            f"{score}/10",
            contact,
            title,
            f"{status_icon} {email_status}",
        ])
    
    print("\n" + "="*100)
    print("LEADS & EMAIL STATUS")
    print("="*100)
    print(tabulate(table_data, headers=["#", "Company", "Score", "Contact", "Title", "Email Status"], tablefmt="grid"))
    print()
    return leads


def display_emails_for_lead(lead):
    """Display all email versions for a specific lead."""
    company = lead[1]
    emails = get_emails_for_lead(lead[0])
    
    if not emails:
        print(f"  ℹ️  No emails generated for {company}")
        return None
    
    table_data = []
    for email in emails:
        email_type = email[7]  # "original", "followup_1", "followup_2", "followup_3"
        status = email[8]
        subject = email[5][:50] + "..." if len(email[5]) > 50 else email[5]
        recipient = email[4]
        
        type_icon = {
            "original": "📧",
            "followup_1": "↩️ 1",
            "followup_2": "↩️ 2",
            "followup_3": "↩️ 3",
        }.get(email_type, "❓")
        
        status_icon = "✅ SENT" if status == "sent" else f"⏳ {status.upper()}"
        
        table_data.append([
            type_icon,
            subject,
            recipient,
            status_icon,
        ])
    
    print(f"\n{'─'*90}")
    print(f"EMAIL SEQUENCE FOR: {company}")
    print(f"{'─'*90}")
    print(tabulate(table_data, headers=["Type", "Subject", "Recipient", "Status"], tablefmt="grid"))
    print()
    return emails


def send_email_interactive():
    """Interactive email sending interface."""
    print("\n" + "="*90)
    print("📧 EMAIL SENDING INTERFACE")
    print("="*90)
    
    leads = display_leads()
    if not leads:
        return
    
    while True:
        try:
            choice = input("\n  Enter lead number to send (or 'q' to quit): ").strip().lower()
            
            if choice == 'q':
                break
            
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(leads):
                print("  ❌ Invalid selection")
                continue
            
            lead = leads[int(choice) - 1]
            company = lead[1]
            lead_id = lead[0]
            
            print(f"\n{'─'*90}")
            print(f"SENDING EMAILS FOR: {company}")
            print(f"{'─'*90}")
            
            emails = display_emails_for_lead(lead)
            if not emails:
                continue
            
            # Show available email types
            available = []
            for email in emails:
                if email[8] != "sent":  # Only show unsent emails
                    available.append((email[7], email))
            
            if not available:
                print(f"  ✅ All emails already sent for {company}")
                continue
            
            print("\nAvailable emails to send:")
            for i, (email_type, email) in enumerate(available, 1):
                print(f"  {i}. {email_type.replace('_', ' ').upper()}")
            
            email_choice = input(f"\nSelect email to send (1-{len(available)}) or 'back': ").strip().lower()
            
            if email_choice == 'back':
                print("\n  Back to lead selection")
                continue
            
            if not email_choice.isdigit() or int(email_choice) < 1 or int(email_choice) > len(available):
                print("  ❌ Invalid selection")
                continue
            
            email_type, email_row = available[int(email_choice) - 1]
            is_followup = email_type != "original"
            
            # Show preview
            print(f"\n{'─'*90}")
            print(f"PREVIEW - {email_type.replace('_', ' ').upper()}")
            print(f"{'─'*90}")
            print(f"To:      {email_row[4]}")
            print(f"Subject: {email_row[5]}")
            print(f"Body:\n{email_row[6][:300]}...\n")
            
            confirm = input("Send this email? (yes/no): ").strip().lower()
            if confirm != 'yes':
                print("  ❌ Send cancelled")
                continue
            
            # Send email
            print(f"\n  📤 Sending {email_type.replace('_', ' ').upper()}...")
            success, result = send_email(email_row, is_followup=is_followup)
            
            if success:
                print(f"  ✅ Email sent successfully!")
                print(f"  🔗 MessageID: {result}")
                update_email_status(lead_id, email_type, "sent")
            else:
                print(f"  ❌ Send failed: {result}")
            
            time.sleep(2)
            
        except KeyboardInterrupt:
            print("\n  Exiting")
            break
        except Exception as e:
            print(f"  ❌ Error: {str(e)}")


def campaign_dashboard():
    """Show campaign statistics."""
    stats = get_campaign_stats()
    
    print("\n" + "="*90)
    print("📊 CAMPAIGN DASHBOARD")
    print("="*90)
    
    dashboard_data = [
        ["Total Leads", stats.get("total_leads", 0)],
        ["Leads with Emails", stats.get("leads_with_emails", 0)],
        ["Originals Sent", stats.get("originals_sent", 0)],
        ["Replies Received", stats.get("replies", 0)],
        ["Pending (Unsent)", stats.get("pending", 0)],
    ]
    
    print(tabulate(dashboard_data, headers=["Metric", "Count"], tablefmt="grid"))
    print()


def reply_checker():
    """Check for new replies."""
    print("\n" + "="*90)
    print("📬 CHECKING FOR REPLIES...")
    print("="*90)
    
    print("\n  Scanning Gmail for new replies...")
    new_replies = check_replies()
    
    if new_replies:
        print(f"\n  ✅ Found {len(new_replies)} new reply/replies!")
        for lead_id, company in new_replies:
            print(f"    • {company}")
    else:
        print("  ℹ️  No new replies")
    
    print()


def run_email_cli():
    """Main CLI interface."""
    print("\n🤖 Starting Email Sending Interface...")
    print("─"*90)
    
    while True:
        print("\n" + "─"*90)
        print("COMMANDS:")
        print("─"*90)
        print("  1. Send emails              (Interactive mode)")
        print("  2. View campaign dashboard  (Statistics)")
        print("  3. Check for replies        (Gmail IMAP scan)")
        print("  4. Exit")
        print("─"*90)
        
        choice = input("\nChoose option (1/2/3/4): ").strip()
        
        if choice == "1":
            send_email_interactive()
        elif choice == "2":
            campaign_dashboard()
        elif choice == "3":
            reply_checker()
        elif choice == "4":
            print("\n  ✅ Goodbye!")
            break
        else:
            print("  ❌ Invalid option")
