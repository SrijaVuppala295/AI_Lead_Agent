"""
discord_bot.py — Discord Campaign Bot
=======================================

COMMANDS:
  /leads           — list all leads with contacts + email status
  /status          — campaign dashboard (generated/sent/replied/pending)
  /sheets          — show all Google Sheet tabs with row counts
  /preview         — preview email sequence for a company
  /send            — send batch of emails (random 60-300s delay, avoid spam)
  /check_replies   — scan Gmail IMAP for replies
  /pending         — show emails ready to send

RATE LIMITING:
  Random delay: 60-300 seconds between sends (anti-spam)
  Randomized each send to avoid detection
  Precise UTC timestamps logged
  Max 50 emails per bot session
  Followup requires original sent first
  All followups use same thread (References header)
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import time
from datetime import datetime

from utils.database import (
    get_all_leads,
    get_emails_for_lead,
    get_emails_by_status,
    get_campaign_stats,
    update_email_status
)
from agents.email_sender import send_email, check_replies


# ── Rate limiting ─────────────────────────────────────────────────────────
import random
RATE_LIMIT_MIN      = 60      # Minimum 60 seconds (anti-spam)
RATE_LIMIT_MAX      = 300     # Maximum 5 minutes
MAX_EMAILS_PER_SESSION = 50
last_send_time      = 0
session_send_count  = 0
used_delays         = set()   # Track used delays to avoid repetition


# ── Bot setup ─────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot     = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"  🤖 Discord bot connected: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"  ✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"  ❌ Sync failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# /leads — List all leads with status
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="leads", description="List all leads with contact and email status")
async def leads_cmd(interaction: discord.Interaction):
    await interaction.response.defer()

    leads = get_all_leads()
    if not leads:
        await interaction.followup.send("⚠️ No leads in database.")
        return

    embeds = []
    chunk  = []

    for lead in leads:
        score        = lead[4] or 0
        company      = lead[1]
        contact      = lead[9]  or "TBD"
        title        = lead[10] or "TBD"
        website      = lead[11] or "TBD"
        email        = lead[13] if len(lead) > 13 else ""
        email_status = lead[14] if len(lead) > 14 else "no_email"

        score_emoji = "🔥" if score >= 7 else "✅"
        email_emoji = {
            "sent":       "📤",
            "replied":    "💬",
            "generated":  "🤖",
            "discovered": "📧",
            "no_email":   "❌",
        }.get(email_status, "❓")

        chunk.append(
            f"{score_emoji} **{company}** `[{score}/10]`\n"
            f"👤 {contact} — {title}\n"
            f"🌐 {website}\n"
            f"{email_emoji} {email or 'No email'} `{email_status}`\n"
        )

        if len(chunk) == 8:
            embed = discord.Embed(
                title="📋 PropTech Leads",
                description="\n".join(chunk),
                color=discord.Color.blue()
            )
            embeds.append(embed)
            chunk = []

    if chunk:
        embed = discord.Embed(
            title="📋 PropTech Leads",
            description="\n".join(chunk),
            color=discord.Color.blue()
        )
        embeds.append(embed)

    for embed in embeds[:5]:
        await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# /status — Campaign dashboard
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="status", description="Email campaign dashboard")
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()

    stats  = get_campaign_stats()
    leads  = get_all_leads()

    total_leads     = len(leads)
    with_email      = sum(1 for l in leads if len(l) > 13 and l[13] and l[13] not in ["", "Not found"])
    no_email        = total_leads - with_email

    embed = discord.Embed(
        title="📊 Strikin Campaign Dashboard",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    # Leads section
    embed.add_field(
        name="👥 Leads",
        value=(
            f"Total: **{total_leads}**\n"
            f"With email: **{with_email}**\n"
            f"No email: **{no_email}**"
        ),
        inline=True
    )

    # Emails section
    embed.add_field(
        name="✉️ Emails",
        value=(
            f"🤖 Generated: **{stats['generated']}**\n"
            f"📤 Sent: **{stats['sent']}**\n"
            f"💬 Replied: **{stats['replied']}**\n"
            f"⏳ Pending: **{stats['pending']}**"
        ),
        inline=True
    )

    # Reply rate
    if stats["sent"] > 0:
        reply_rate = round(stats["replied"] / stats["sent"] * 100, 1)
        embed.add_field(
            name="📈 Reply Rate",
            value=f"**{reply_rate}%**",
            inline=True
        )

    # Session info
    embed.add_field(
        name="⚡ Session",
        value=f"Sent this session: **{session_send_count}/{MAX_EMAILS_PER_SESSION}**",
        inline=False
    )

    embed.set_footer(text="Use /send <company> to send emails | /check_replies to scan inbox")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# /sheets — Show Google Sheets info
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="sheets", description="Show Google Sheets tabs and row counts")
async def sheets_cmd(interaction: discord.Interaction):
    await interaction.response.defer()

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    leads    = get_all_leads()

    ROWS_PER_SHEET = 500
    total_leads    = len(leads)
    sheets_needed  = max(1, (total_leads + ROWS_PER_SHEET - 1) // ROWS_PER_SHEET)

    embed = discord.Embed(
        title="📊 Google Sheets Status",
        color=discord.Color.green()
    )

    for i in range(1, sheets_needed + 1):
        start = (i - 1) * ROWS_PER_SHEET + 1
        end   = min(i * ROWS_PER_SHEET, total_leads)
        name  = "PropTech Leads" if i == 1 else f"PropTech Leads {i}"
        rows_in_sheet = max(0, end - start + 1)

        status = "✅ Active" if rows_in_sheet > 0 else "📭 Empty"
        embed.add_field(
            name=f"Sheet {i}: {name}",
            value=f"Rows: **{rows_in_sheet}** / 500  {status}",
            inline=False
        )

    embed.add_field(
        name="🔗 Spreadsheet Link",
        value=f"[Open Google Sheets](https://docs.google.com/spreadsheets/d/{sheet_id})",
        inline=False
    )
    embed.set_footer(text="New sheet auto-created at 500 rows")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# /preview — Preview emails for a company
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="preview", description="Preview email sequence for a company")
@app_commands.describe(company="Company name (partial match ok)")
async def preview_cmd(interaction: discord.Interaction, company: str):
    await interaction.response.defer()

    leads    = get_all_leads()
    matching = [l for l in leads if company.lower() in l[1].lower()]

    if not matching:
        await interaction.followup.send(f"⚠️ No lead found matching `{company}`")
        return

    lead     = matching[0]
    lead_id  = lead[0]
    emails   = get_emails_for_lead(lead_id)

    if not emails:
        await interaction.followup.send(
            f"⚠️ No emails generated for `{lead[1]}` yet.\n"
            f"Run **Option 2** from menu.py to generate emails first."
        )
        return

    await interaction.followup.send(
        f"📧 Email sequence for **{lead[1]}** ({len(emails)} emails):"
    )

    status_emoji = {
        "generated": "🤖", "sent": "📤",
        "replied": "💬",   "pending": "⏳"
    }

    for em in emails:
        etype   = em[7]
        subject = em[5]
        body    = em[6]
        status  = em[8]
        to_addr = em[4]

        emoji   = status_emoji.get(status, "❓")
        preview = body[:400].replace("\n", "\n> ") if body else "No body"

        embed = discord.Embed(
            title=f"{emoji} {etype.replace('_',' ').upper()}",
            color={
                "generated": discord.Color.orange(),
                "sent":      discord.Color.green(),
                "replied":   discord.Color.gold(),
                "pending":   discord.Color.greyple(),
            }.get(status, discord.Color.blue())
        )
        embed.add_field(name="📬 To",      value=to_addr or "No email", inline=True)
        embed.add_field(name="📊 Status",  value=f"{emoji} {status}",   inline=True)
        embed.add_field(name="📌 Subject", value=subject,                inline=False)
        embed.add_field(name="📝 Preview", value=f"> {preview}",         inline=False)

        await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# /send — Batch send emails with random rate limiting (reads from Google Sheets)
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="send", description="Batch send emails with anti-spam random delays (Google Sheets source)")
@app_commands.describe(
    email_type="Email type to send",
    limit="How many emails to send (max 50)",
    sheet_name="Google Sheet tab name (for reference)"
)
@app_commands.choices(email_type=[
    app_commands.Choice(name="Original (first email)",   value="original"),
    app_commands.Choice(name="Followup 1 (day 3)",       value="followup_1"),
    app_commands.Choice(name="Followup 2 (day 7)",       value="followup_2"),
    app_commands.Choice(name="Followup 3 (day 14 final)",value="followup_3"),
])
async def send_cmd(interaction: discord.Interaction,
                   email_type: str,
                   limit: int,
                   sheet_name: str):
    from agents.sheets_reader import get_all_leads_from_sheets_async, get_emails_from_sheets_async, update_email_status_sheets_async
    from utils.database import get_email_by_company_and_type
    
    global last_send_time, session_send_count, used_delays
    
    await interaction.response.defer()
    
    # ── Validate inputs ───────────────────────────────────────────────────
    if limit < 1 or limit > 50:
        await interaction.followup.send("⚠️ Limit must be between 1-50")
        return
    
    if session_send_count >= MAX_EMAILS_PER_SESSION:
        await interaction.followup.send(
            f"🛑 Session limit reached ({MAX_EMAILS_PER_SESSION} emails).\n"
            f"Restart the bot to reset counter."
        )
        return
    
    # ── Get all leads from Google Sheets (source of truth) - ASYNC ────────
    all_leads = await get_all_leads_from_sheets_async()
    
    if not all_leads:
        await interaction.followup.send(
            f"⚠️ No leads found in Google Sheets.\n"
            f"Make sure the Leads tab has data."
        )
        return
    
    # Filter leads that have this email type and meet prerequisites
    leads_to_send = []
    all_db_emails = get_emails_by_status()
    
    for lead in all_leads:
        emails = await get_emails_from_sheets_async(lead["company_name"])
        if email_type not in emails:
            continue
        
        company_name = lead["company_name"]
        
        # Check database status (source of truth)
        email_id = get_email_by_company_and_type(company_name, email_type)
        if not email_id:
            continue
            
        email_record = next((e for e in all_db_emails if e[0] == email_id), None)
        if not email_record:
            continue
        
        email_status = email_record[8]  # status at index 8
        
        # Don't send if already sent
        if email_status == "sent":
            continue
        
        # Check followup prerequisites
        if email_type != "original":
            # For followups, check if previous email was replied or sent
            prerequisite_map = {
                "followup_1": "original",
                "followup_2": "followup_1",
                "followup_3": "followup_2",
            }
            prereq_type = prerequisite_map[email_type]
            prereq_id = get_email_by_company_and_type(company_name, prereq_type)
            
            if not prereq_id:
                continue  # Prerequisite doesn't exist
            
            prereq_record = next((e for e in all_db_emails if e[0] == prereq_id), None)
            if not prereq_record:
                continue
            
            prereq_status = prereq_record[8]
            # Followup can proceed if prerequisite is replied or sent
            if prereq_status not in ["replied", "sent"]:
                continue
        
        # Only include if email address exists
        if lead["email"] and "@" in lead["email"]:
            leads_to_send.append((lead, emails[email_type]))
    
    if not leads_to_send:
        await interaction.followup.send(
            f"⚠️ No `{email_type}` emails ready to send.\n"
            f"All emails of this type have already been sent."
        )
        return
    
    # Limit to request amount and session cap
    to_send = min(limit, len(leads_to_send), MAX_EMAILS_PER_SESSION - session_send_count)
    batch = leads_to_send[:to_send]
    
    # ── Show batch summary ────────────────────────────────────────────────
    start_embed = discord.Embed(
        title=f"📧 BATCH SEND: {email_type.upper()}",
        description=f"Sheet: `{sheet_name}`\nEmails: {len(batch)} | Limit: {limit}",
        color=discord.Color.blue()
    )
    start_embed.add_field(
        name="⏱️ Timing",
        value=f"Random delays: {RATE_LIMIT_MIN}-{RATE_LIMIT_MAX}s\nAnti-spam randomization enabled",
        inline=False
    )
    start_embed.add_field(
        name="📍 Source",
        value="Reading latest emails & addresses from Google Sheets ✅",
        inline=False
    )
    await interaction.followup.send(embed=start_embed)
    
    # ── Send sequentially with random delays BETWEEN emails ────────────────
    sent_count = 0
    failed_count = 0
    send_log = []
    
    for idx, (lead, email_info) in enumerate(batch, 1):
        is_followup = email_type != "original"
        
        company_name = lead["company_name"]
        contact_email = lead["email"]  # LIVE from Google Sheets
        subject = email_info["subject"]
        body = email_info["body"]
        
        # Show send info with precise timestamp
        send_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        send_log.append(f"[{idx}/{len(batch)}] {company_name} → {contact_email} at {send_time}")
        
        send_msg = discord.Embed(
            title=f"📤 Sending {idx}/{len(batch)}",
            description=f"**{company_name}**\nTo: `{contact_email}`",
            color=discord.Color.orange()
        )
        send_msg.add_field(
            name="Subject", 
            value=subject[:70] + "..." if len(subject) > 70 else subject, 
            inline=False
        )
        await interaction.followup.send(embed=send_msg)
        
        # Get email ID from database for status tracking and threading
        email_id = get_email_by_company_and_type(company_name, email_type)
        
        # Build email tuple for send_email function
        # Structure: (id, lead_id, company, contact_name, contact_email, subject, body, type, status, message_id, thread_id, ...)
        email_row = (
            email_id,           # [0] id (for status update)
            None,               # [1] lead_id (not critical for sending)
            company_name,       # [2] company_name
            lead["contact_name"],  # [3] contact_name
            contact_email,      # [4] contact_email
            subject,            # [5] subject
            body,               # [6] body
            email_type,         # [7] type
            "generated",        # [8] status
            None,               # [9] message_id
            None,               # [10] thread_id (will be set for followups)
        )
        
        # Send email immediately (no delay before first)
        success, result = send_email(email_row, is_followup=is_followup)
        
        if success:
            sent_count += 1
            session_send_count += 1
            last_send_time = time.time()
            
            # send_email already updated the database, just update Google Sheets - ASYNC
            await update_email_status_sheets_async(company_name, email_type, "sent ✉️")
            
            result_embed = discord.Embed(
                title="✅ Sent Successfully",
                description=f"MessageID: `{result}`\nTime: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                color=discord.Color.green()
            )
            result_embed.add_field(name="Session Progress", value=f"{session_send_count}/{MAX_EMAILS_PER_SESSION}", inline=False)
            result_embed.add_field(name="📊 Status Updated", value="Database ✅ | Google Sheets ✅", inline=False)
            await interaction.followup.send(embed=result_embed)
            
            # Add post-send delay (8-20s) to avoid Gmail spam detection
            from utils.rate_limiter import get_delay
            post_delay = get_delay("email_send")
            print(f"  ⏱  Post-send delay: {post_delay:.4f}s")
            await asyncio.sleep(post_delay)
        else:
            failed_count += 1
            result_embed = discord.Embed(
                title="❌ Send Failed",
                description=f"Error: {result}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=result_embed)
        
        # Add random delay BETWEEN emails (not before first, not after last)
        if idx < len(batch):
            while True:
                delay = random.randint(RATE_LIMIT_MIN, RATE_LIMIT_MAX)
                if delay not in used_delays:
                    used_delays.add(delay)
                    break
            
            delay_embed = discord.Embed(
                title="⏳ Waiting Before Next Email",
                description=f"Random delay: **{delay}s** to avoid spam detection",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=delay_embed)
            await asyncio.sleep(delay)
    
    # ── Final summary ─────────────────────────────────────────────────────
    summary_embed = discord.Embed(
        title="📊 BATCH COMPLETE",
        description=f"Sheet: `{sheet_name}`",
        color=discord.Color.gold()
    )
    summary_embed.add_field(name="✅ Sent", value=sent_count, inline=True)
    summary_embed.add_field(name="❌ Failed", value=failed_count, inline=True)
    summary_embed.add_field(name="Session Total", value=f"{session_send_count}/{MAX_EMAILS_PER_SESSION}", inline=True)
    summary_embed.add_field(name="📝 Log", value="\n".join(send_log) if send_log else "None", inline=False)
    await interaction.followup.send(embed=summary_embed)


# ═══════════════════════════════════════════════════════════════════════════
# /check_replies — Scan Gmail for replies
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="check_replies", description="Scan Gmail inbox for replies to sent emails")
async def check_replies_cmd(interaction: discord.Interaction):
    from agents.sheets_reader import update_email_status_sheets_async
    
    await interaction.response.defer()

    await interaction.followup.send("🔍 Scanning Gmail inbox for replies...")

    replied = check_replies()

    if not replied:
        await interaction.followup.send(
            "📭 No new replies found.\n"
            "Tip: Make sure you sent emails first using `/send`"
        )
        return

    # Update Google Sheets for each reply - ASYNC
    for r in replied:
        company_name = r["company_name"]
        # Mark the original email as replied in Google Sheets
        await update_email_status_sheets_async(company_name, "original", "replied ✅")

    embed = discord.Embed(
        title=f"💬 {len(replied)} New Replies Found!",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(
        name="✅ Status Updated",
        value="Database ✅ | Google Sheets ✅\nFollowups can now be sent!",
        inline=False
    )
    
    for r in replied:
        embed.add_field(
            name=f"🏢 {r['company_name']}",
            value=(
                f"👤 {r['contact_name']}\n"
                f"📧 {r['from']}"
            ),
            inline=False
        )
    embed.set_footer(text="Reply status updated in DB and Google Sheets")
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# /pending — Show emails ready to send
# ═══════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="pending", description="Show all emails ready to send")
async def pending_cmd(interaction: discord.Interaction):
    await interaction.response.defer()

    generated = get_emails_by_status("generated")

    if not generated:
        await interaction.followup.send(
            "✅ No pending emails — all generated emails have been sent!"
        )
        return

    lines = []
    for em in generated[:20]:
        type_emoji = "🆕" if em[7] == "original" else "↩️"
        lines.append(
            f"{type_emoji} **{em[2]}** — `{em[7]}` — `{em[4] or 'no email'}`"
        )

    embed = discord.Embed(
        title=f"⏳ {len(generated)} Emails Ready to Send",
        description="\n".join(lines),
        color=discord.Color.yellow()
    )
    embed.set_footer(
        text="Use /send <company> original  |  /send <company> followup_1"
    )
    await interaction.followup.send(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# RUN BOT
# ═══════════════════════════════════════════════════════════════════════════

def run_discord_bot():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("  ❌ DISCORD_BOT_TOKEN not set in .env")
        return
    print("\n🤖 Starting Discord Campaign Bot...")
    print("─"*50)
    print("  Commands available:")
    print("  /send          → batch send emails (reads live from Google Sheets)")
    print("  /leads         → list all leads + email status")
    print("  /status        → campaign dashboard")
    print("  /sheets        → Google Sheets tab info")
    print("  /preview       → preview email sequence")
    print("  /check_replies → scan Gmail for replies")
    print("  /pending       → emails ready to send")
    print("─"*50)
    print("  📍 Google Sheets is the source of truth")
    print("  Press Ctrl+C to stop\n")
    bot.run(token)