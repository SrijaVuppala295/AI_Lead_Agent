"""
scheduler.py — Automated Daily Runner
======================================
Runs the full lead gen pipeline automatically every day at 9AM.

HOW TO USE:
  Run once: python scheduler.py
  Keeps running in background — fires every day at 9AM IST

SCHEDULE:
  Daily 9:00 AM IST → full pipeline run
  Runs immediately on start (so you see it working right away)
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

from main import run_agent


def scheduled_run():
    print(f"\n⏰ SCHEDULED RUN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    run_agent()


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Run every day at 9AM IST
    scheduler.add_job(
        scheduled_run,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_lead_gen",
        name="Daily Lead Gen Run"
    )

    print("⏰ SCHEDULER STARTED")
    print("   Runs daily at 9:00 AM IST")
    print("   Press Ctrl+C to stop\n")

    # Run immediately on start
    print("▶️  Running now on startup...")
    scheduled_run()

    # Then keep running on schedule
    scheduler.start()