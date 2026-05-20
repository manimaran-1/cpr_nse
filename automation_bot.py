import time
import os
import pytz
import logging
from datetime import datetime
import pandas as pd
import requests
import scanner
import data_loader
import config
import reporter

# Configuration for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Secure Configuration from Secrets / Env Vars
BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
CHAT_ID = config.TELEGRAM_CHAT_ID
SCAN_UNIVERSE = config.SCAN_UNIVERSE
SCAN_INTERVAL = config.SCAN_INTERVAL
SEND_IF_EMPTY = config.SEND_IF_EMPTY
CLOSE_METHOD = config.CLOSE_METHOD
TARGET_SESSION = config.TARGET_SESSION

# Flag: running in GitHub Actions (skip market hours check, run once)
IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"

def validate_config():
    """Ensure all required configuration is present."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("🛑 CRITICAL: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        return False
    return True

def send_telegram_message(message, retries=3):
    """Sends a text message via Telegram Bot API with retry logic."""
    # Telegram text message limit: 4096 characters
    if len(message) > 4096:
        message = message[:4090] + "\n..."
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(retries):
        try:
            payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error sending message (Attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return False

def send_telegram_document(file_path, caption, retries=3):
    """Sends a document (CSV) via Telegram Bot API with retry logic."""
    # Telegram caption limit: 1024 characters
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    for attempt in range(retries):
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}
                response = requests.post(url, files=files, data=data, timeout=30)
                if response.status_code == 200:
                    return True
                logger.error(f"Telegram API Error (Attempt {attempt+1}/{retries}): {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending document (Attempt {attempt+1}/{retries}): {e}")

        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return False

def run_scan():
    """Executes the stock scan and sends results to Telegram."""
    now = datetime.now(IST)

    # === MARKET STATUS CHECK (skip in CI — runs after market close) ===
    if not IS_CI and not data_loader.is_market_open():
        logger.info("Market is closed (weekend/off-hours). Skipping scan.")
        if SEND_IF_EMPTY:
            send_telegram_message(
                f"ℹ️ *Market Closed*\n"
                f"📊 Status: Weekend/Off-hours\n"
                f"⏰ {now.strftime('%H:%M %d-%b-%Y')} IST\n"
                f"⏭️ Next scan during market hours."
            )
        return

    # Market Open Sync Guard (skip in CI)
    if not IS_CI and now.hour == 9 and 15 <= now.minute < 16:
        logger.info("Market just opened. Waiting 60s for data synchronization...")
        time.sleep(60)
        now = datetime.now(IST)

    logger.info(f"Starting Scan: {SCAN_UNIVERSE} ({SCAN_INTERVAL}) | Method: {CLOSE_METHOD} | Session: {TARGET_SESSION}")

    try:
        # Resolve symbols
        if SCAN_UNIVERSE == "Nifty 500":
            symbols = data_loader.get_nifty500_symbols()
        elif SCAN_UNIVERSE == "Nifty 200":
            symbols = data_loader.get_nifty200_symbols()
        else:
            symbols = data_loader.get_index_constituents(SCAN_UNIVERSE)

        if not symbols:
            logger.warning(f"No symbols found for {SCAN_UNIVERSE}. Aborting scan.")
            return

        send_telegram_message(
            f"🔍 *NSE Scanner 2.0 Started*\n"
            f"📊 Universe: {SCAN_UNIVERSE}\n"
            f"⏰ Timeframe: {SCAN_INTERVAL}\n"
            f"🎯 Session: {TARGET_SESSION}\n"
            f"💰 Method: {CLOSE_METHOD}\n"
            f"🔢 Symbols: {len(symbols)}"
        )

        # Execute scanner
        results_df = scanner.scan_market(
            symbols,
            interval=SCAN_INTERVAL,
            close_method=CLOSE_METHOD,
            target_session=TARGET_SESSION
        )

        if not results_df.empty:
            results_df = results_df.sort_values(by='Signal Time', ascending=False)

            # Use Absolute Path for temporary CSV (Critical for system-level scheduling)
            base_dir = os.path.dirname(os.path.abspath(__file__))
            filename = f"scan_results_{now.strftime('%Y%m%d_%H%M%S')}.csv"
            file_path = os.path.join(base_dir, filename)

            results_df.to_csv(file_path, index=False)

            # Generate Multi-Part Analysis Report
            report_parts = reporter.generate_report(results_df, SCAN_UNIVERSE, SCAN_INTERVAL)

            # Send the CSV document with scan parameters in caption
            caption = (
                f"📊 {SCAN_UNIVERSE} | {SCAN_INTERVAL}\n"
                f"🎯 {TARGET_SESSION} | {CLOSE_METHOD}\n"
                f"📈 {len(results_df)} signals | {now.strftime('%d-%b-%Y %H:%M')} IST"
            )
            send_telegram_document(file_path, caption)

            # Send all report parts as separate text messages
            for part in report_parts:
                send_telegram_message(part)

            logger.info(f"Results sent to Telegram: {len(results_df)} signals.")

            # Cleanup
            if os.path.exists(file_path):
                os.remove(file_path)
        else:
            if SEND_IF_EMPTY:
                msg = (
                    f"ℹ️ *Scan Completed*\n"
                    f"📊 *Universe:* {SCAN_UNIVERSE}\n"
                    f"⏰ *Timeframe:* {SCAN_INTERVAL}\n"
                    f"🎯 *Session:* {TARGET_SESSION}\n"
                    f"⚠️ No matches found at this time."
                )
                send_telegram_message(msg)
            logger.info("Scan complete - 0 signals found.")

    except Exception as e:
        logger.exception(f"Unexpected error in run_scan: {e}")
        send_telegram_message(f"❌ *Scanner Error:* {str(e)}")

def main():
    if not validate_config():
        logger.error("Configuration validation failed. Exiting.")
        return

    logger.info("========================================")
    logger.info(" NSE Stock Scanner 2.0 - Automation Bot ")
    logger.info("========================================")
    logger.info(f"Universe: {SCAN_UNIVERSE} | Interval: {SCAN_INTERVAL}")
    logger.info(f"Method: {CLOSE_METHOD} | Session: {TARGET_SESSION}")
    if IS_CI:
        logger.info("Running in CI mode — skipping market hours check")

    # Set data source from env or default to auto
    ds = os.environ.get("DATA_SOURCE", "auto")
    data_loader.set_data_source(ds)
    logger.info(f"📡 Data source: {ds}")
    
    # Check for immediate run
    if os.environ.get("TEST_RUN") == "1" or os.environ.get("GITHUB_ACTIONS") == "true":
        logger.info("Triggering initial scan (TEST_RUN/CI)...")
        run_scan()
        if os.environ.get("ONCE") == "1" or os.environ.get("GITHUB_ACTIONS") == "true":
            return

    # Specific Schedule: 9:16, 10:16, ..., 15:16 (3:16 PM)
    SCHEDULED_HOURS = [9, 10, 11, 12, 13, 14, 15]
    SCHEDULE_MINUTE = 16
    
    last_run_id = None # Format: "YYYY-MM-DD-HH"

    while True:
        try:
            now = datetime.now(IST)
            is_weekday = now.weekday() < 5 # 0=Mon, 4=Fri
            
            if is_weekday:
                current_run_id = now.strftime("%Y-%m-%d-%H")
                
                # Check if current hour and minute match our target
                if now.hour in SCHEDULED_HOURS and now.minute == SCHEDULE_MINUTE:
                    if last_run_id != current_run_id:
                        logger.info(f"Target time reached: {now.strftime('%H:%M')}. Starting scheduled scan.")
                        run_scan()
                        last_run_id = current_run_id
                
                # Close message/reset at end of day
                elif now.hour == 15 and now.minute > SCHEDULE_MINUTE and last_run_id == current_run_id:
                    logger.info("Market session processing complete for today.")
                    send_telegram_message(
                        f"🏁 *Market Closed — End of Day*\n"
                        f"📅 {now.strftime('%d-%b-%Y')}\n"
                        f"✅ All scheduled scans completed."
                    )
                    last_run_id = f"{current_run_id}-CLOSED" # Prevent re-trigger if restarted
                    
            # Daily reset for last_run_id if needed (though current_run_id handles it)
            if now.hour == 0 and now.minute == 0:
                last_run_id = None
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(60)
            
        time.sleep(30)

if __name__ == "__main__":
    main()
