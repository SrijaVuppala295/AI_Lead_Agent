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

import logging
import sys
import signal
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("scheduler")

load_dotenv()

from main import run_agent

def scheduled_run():
    logger.info("⏰ SCHEDULED RUN STARTED")
    try:
        run_agent()
        logger.info("✅ SCHEDULED RUN COMPLETED")
    except Exception as e:
        logger.error(f"❌ SCHEDULED RUN FAILED: {e}", exc_info=True)

def handle_exit(signum, frame):
    logger.info("🛑 Received termination signal. Shutting down scheduler...")
    if scheduler.running:
        scheduler.shutdown()
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers for clean shutdown in Docker/Railway
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Run every day at 9AM IST
    scheduler.add_job(
        scheduled_run,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_lead_gen",
        name="Daily Lead Gen Run"
    )

    logger.info("⏰ SCHEDULER STARTED")
    logger.info("   Schedule: Daily at 9:00 AM IST")

    # Run immediately on start
    logger.info("▶️  Running immediate startup task...")
    scheduled_run()

    # Then keep running on schedule
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
