import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- TELEGRAM CONFIGURATION ---
# These are now loaded from the .env file or environment variables.
TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

# --- SCANNER CONFIGURATION ---
SCAN_UNIVERSE = os.environ.get("SCAN_UNIVERSE", "Nifty 500")
SCAN_INTERVAL = os.environ.get("SCAN_INTERVAL", "1h")
SEND_IF_EMPTY = os.environ.get("SEND_IF_EMPTY", "True").lower() == "true"

# --- STRATEGY THRESHOLDS ---
STRATEGY_CONFIG = {
    "EMA": [5, 9, 21],          # EMA lengths for price comparison
    "STOCH_RSI_K_MIN": 70,      # Minimum Stoch RSI K level
    "SMI_MIN": 30,              # Minimum SMI level
    "MACD_MIN": 0.75,           # Minimum MACD level
    "STOCH_RSI": {
        "length": 14,
        "rsi_length": 14,
        "k": 3,
        "d": 3
    },
    "SMI": {
        "length": 10,
        "smooth": 3
    },
    "MACD": {
        "fast": 12,
        "slow": 26,
        "signal": 9
    }
}

# --- NEW 3-SCORE SYSTEM CONFIG ---
SCORE_CONFIG = {
    # Score thresholds for alert generation
    "IGNITION_THRESHOLD": 40,       # Min ignition score (0-100) to fire alert
    "INTRADAY_THRESHOLD": 45,       # Min intraday score (0-100) to fire alert
    "SWING_THRESHOLD": 40,          # Min swing score (0-100) to fire alert

    # Overextension detection (% distance from EMA21)
    "OVEREXTENSION_WARN": 5.0,      # Yellow flag — stock is stretched
    "OVEREXTENSION_KILL": 8.0,      # Red flag — DO NOT CHASE

    # Exhaustion thresholds for penalty deductions
    "RSI_EXHAUSTION": 78,           # RSI above this = momentum exhausting
    "RSI_OVERBOUGHT": 75,           # Used in Ignition penalty
    "STOCH_EXHAUSTION": 90,         # StochRSI K above this = topped out

    # Volume thresholds
    "RVOL_ELEVATED": 1.5,           # Attention-worthy volume
    "RVOL_INSTITUTIONAL": 2.5,      # High-conviction institutional flow

    # Intraday-specific
    "VWAP_MAX_DISTANCE_PCT": 4.0,   # Max % above VWAP before penalty
    "DAY_CHANGE_MAX_PCT": 5.0,      # Max intraday change before penalty
    "RSI_INTRADAY_SWEET_LOW": 55,   # Ideal RSI range lower bound
    "RSI_INTRADAY_SWEET_HIGH": 72,  # Ideal RSI range upper bound

    # Swing-specific
    "BBW_SQUEEZE_THRESHOLD": 0.04,  # BB Width below this = squeeze
    "BBW_EXPANDED_THRESHOLD": 0.10, # BB Width above this = move may be done
    "REL_STRENGTH_MIN": -2.0,       # Below this = underperforming market

    # Candle selection for quality (15m = best signal-to-noise for NSE intraday)
    "INTRADAY_INTERVAL": "15m",
    "SWING_INTERVAL": "1d",
}

