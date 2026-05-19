# NSE2 Stock Scanner — Complete Build Prompt

## SYSTEM PROMPT FOR AI

You are building an NSE (National Stock Exchange of India) stock scanner. Build EXACTLY as specified below. Do NOT add features not listed. Do NOT change function signatures. Do NOT use different library APIs than specified. Follow every detail exactly.

---

## STEP 1: Create Project Directory Structure

```bash
mkdir -p nse2_automation/.streamlit
mkdir -p nse2_automation/cache/ohlcv
cd nse2_automation
```

Files to create (in this exact order):
1. requirements.txt
2. .env (user fills in)
3. .gitignore
4. .streamlit/config.toml
5. .streamlit/secrets.toml.example
6. config.py
7. auth_handler.py
8. indicators.py
9. data_loader.py
10. scanner.py
11. reporter.py
12. app.py
13. automation_bot.py
14. run_localhost.sh
15. git_push.sh

---

## STEP 2: requirements.txt

```
streamlit
pandas
numpy
fyers-apiv3
yfinance
python-dotenv
pyotp
requests
pytz
pandas-ta-classic
```

---

## STEP 3: config.py — EXACT COPY

```python
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

SCAN_UNIVERSE = os.environ.get("SCAN_UNIVERSE", "Nifty 500")
SCAN_INTERVAL = os.environ.get("SCAN_INTERVAL", "1h")
SEND_IF_EMPTY = os.environ.get("SEND_IF_EMPTY", "True").lower() == "true"

STRATEGY_CONFIG = {
    "EMA": [5, 9, 21],
    "STOCH_RSI_K_MIN": 70,
    "SMI_MIN": 30,
    "MACD_MIN": 0.75,
    "STOCH_RSI": {"length": 14, "rsi_length": 14, "k": 3, "d": 3},
    "SMI": {"length": 10, "smooth": 3},
    "MACD": {"fast": 12, "slow": 26, "signal": 9}
}

SCORE_CONFIG = {
    "IGNITION_THRESHOLD": 40,
    "INTRADAY_THRESHOLD": 45,
    "SWING_THRESHOLD": 40,
    "OVEREXTENSION_WARN": 5.0,
    "OVEREXTENSION_KILL": 8.0,
    "RSI_EXHAUSTION": 78,
    "RSI_OVERBOUGHT": 75,
    "STOCH_EXHAUSTION": 90,
    "RVOL_ELEVATED": 1.5,
    "RVOL_INSTITUTIONAL": 2.5,
    "VWAP_MAX_DISTANCE_PCT": 4.0,
    "DAY_CHANGE_MAX_PCT": 5.0,
    "RSI_INTRADAY_SWEET_LOW": 55,
    "RSI_INTRADAY_SWEET_HIGH": 72,
    "BBW_SQUEEZE_THRESHOLD": 0.04,
    "BBW_EXPANDED_THRESHOLD": 0.10,
    "REL_STRENGTH_MIN": -2.0,
    "INTRADAY_INTERVAL": "15m",
    "SWING_INTERVAL": "1d",
}
```

---

## STEP 4: auth_handler.py — EXACT COPY

```python
import os
import time
import logging
import threading
import pyotp
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class FyersAuthHandler:
    def __init__(self, env_path=None):
        if env_path is None:
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        self.env_path = env_path
        self._reload_env()
        self.fyers = None
        self._lock = threading.Lock()
        self._last_validated = 0

    def _reload_env(self):
        load_dotenv(self.env_path, override=True)
        self.client_id = os.getenv("FYERS_CLIENT_ID")
        self.secret_key = os.getenv("FYERS_SECRET_KEY")
        self.redirect_uri = os.getenv("FYERS_REDIRECT_URI")
        self.access_token = os.getenv("FYERS_ACCESS_TOKEN")
        self.fy_id = os.getenv("FYERS_ID")
        self.pin = os.getenv("FYERS_PIN")
        self.totp_secret = os.getenv("FYERS_TOTP_SECRET")

    def get_client(self):
        with self._lock:
            if self.fyers and (time.time() - self._last_validated < 300):
                return self.fyers
            self._reload_env()
            for attempt in range(3):
                if self.access_token:
                    client = fyersModel.FyersModel(
                        client_id=self.client_id, is_async=False,
                        token=self.access_token, log_path="/tmp"
                    )
                    try:
                        profile = client.get_profile()
                        if profile.get("s") == "ok":
                            self.fyers = client
                            self._last_validated = time.time()
                            logger.info("✅ Fyers token validated successfully")
                            return self.fyers
                        else:
                            logger.warning(f"⚠️ Fyers Token invalid: {profile.get('message')}")
                            self.access_token = None
                    except Exception as e:
                        logger.warning(f"⚠️ Error validating token: {e}")
                if self.fy_id and self.pin and self.totp_secret:
                    logger.info(f"🔄 Attempting auto-login (attempt {attempt + 1}/3)...")
                    if self.perform_automated_login():
                        self._reload_env()
                        time.sleep(1)
                        continue
                    else:
                        logger.warning(f"⚠️ Auto-login attempt {attempt + 1} failed")
                        if attempt < 2:
                            time.sleep(2)
                else:
                    break
            self._print_auth_instructions()
            return None

    def get_login_url(self):
        if self.client_id and self.redirect_uri:
            import urllib.parse
            return f"https://api-t1.fyers.in/api/v3/generate-authcode?client_id={self.client_id}&redirect_uri={urllib.parse.quote(self.redirect_uri)}&response_type=code&state=None"
        return "#"

    def handle_auth_code(self, auth_code):
        try:
            session = fyersModel.SessionModel(
                client_id=self.client_id, secret_key=self.secret_key,
                redirect_uri=self.redirect_uri, response_type="code",
                grant_type="authorization_code"
            )
            session.set_token(auth_code)
            resp = session.generate_token()
            if resp.get("s") == "ok":
                new_token = resp["access_token"]
                self._update_env_file("FYERS_ACCESS_TOKEN", new_token)
                self.access_token = new_token
                return True, "Token saved"
            return False, resp.get("message", "Unknown error")
        except Exception as e:
            return False, str(e)

    def _update_env_file(self, key, value):
        lines = []
        found = False
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f'{key}="{value}"\n'
                    found = True
                    break
        if not found:
            lines.append(f'{key}="{value}"\n')
        with open(self.env_path, 'w') as f:
            f.writelines(lines)

    def perform_automated_login(self):
        import requests
        try:
            logger.info(f"🚀 Attempting automated headless login for {self.fy_id}...")
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json"
            }
            totp = pyotp.TOTP(self.totp_secret).now()
            base_urls = ["https://api-t1.fyers.in", "https://api.fyers.in"]
            request_key = None
            for base in base_urls:
                for path in ["/api/v3/send_login_otp", "/api/v3/send_login_otp_v2"]:
                    url = base + path
                    try:
                        res = requests.post(url, json={"fy_id": self.fy_id, "app_id": "2"}, headers=headers, timeout=10)
                        if res.status_code == 200:
                            request_key = res.json().get("request_key")
                            if request_key:
                                logger.info(f"✅ Step 1 OK: {url}")
                                break
                    except: pass
                if request_key:
                    break
            if not request_key:
                logger.warning("⚠️ Headless login Step 1 failed - all OTP endpoints unavailable")
                return False
            for base in base_urls:
                for path in ["/api/v3/verify_totp", "/api/v3/verify_totp_v2"]:
                    url = base + path
                    try:
                        res = requests.post(url, json={"request_key": request_key, "totp": totp}, headers=headers, timeout=10)
                        if res.status_code == 200:
                            new_key = res.json().get("request_key")
                            if new_key:
                                request_key = new_key
                                break
                    except: pass
                else:
                    continue
                break
            auth_code = None
            for base in base_urls:
                for path in ["/api/v3/verify_pin", "/api/v3/verify_pin_v2"]:
                    url = base + path
                    try:
                        res = requests.post(url, json={"request_key": request_key, "identity_type": "pin", "identifier": self.pin}, headers=headers, timeout=10)
                        if res.status_code == 200:
                            auth_code = res.json().get("data", {}).get("authorization_code")
                            if auth_code:
                                break
                    except: pass
                if auth_code:
                    break
            if auth_code:
                success, msg = self.handle_auth_code(auth_code)
                if success:
                    logger.info("✅ Token saved to .env")
                return success
            return False
        except Exception as e:
            logger.error(f"❌ Automated login failed: {e}")
            return False

    def _print_auth_instructions(self):
        logger.error("FYERS AUTHENTICATION REQUIRED")
        if self.access_token:
            logger.info(f"Login URL: {self.get_login_url()}")

_handler = FyersAuthHandler()

def get_fyers_client():
    return _handler.get_client()
```

---

## STEP 5: indicators.py — EXACT COPY

```python
import pandas as pd
import numpy as np
import pandas_ta_classic as ta


def calculate_heikin_ashi(df):
    """Calculate Heikin Ashi candles."""
    ha_df = df.copy()
    ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_df['ha_open'] = 0.0
    ha_df.iloc[0, ha_df.columns.get_loc('ha_open')] = df['open'].iloc[0]
    for i in range(1, len(ha_df)):
        ha_df.iloc[i, ha_df.columns.get_loc('ha_open')] = (ha_df.iloc[i-1]['ha_open'] + ha_df.iloc[i-1]['ha_close']) / 2
    ha_df['ha_high'] = pd.concat([ha_df['ha_open'], ha_df['ha_close'], df['high']], axis=1).max(axis=1)
    ha_df['ha_low'] = pd.concat([ha_df['ha_open'], ha_df['ha_close'], df['low']], axis=1).min(axis=1)
    return ha_df


def calculate_ema(df, length):
    """EMA via pandas-ta-classic. Falls back to native ewm if data too short."""
    if len(df) < length:
        return df['close'].ewm(span=length, adjust=False).mean()
    result = ta.ema(df['close'], length=length, sma=False)
    if result is None:
        return df['close'].ewm(span=length, adjust=False).mean()
    return result.fillna(0)


def calculate_stoch_rsi(df, length=14, rsi_length=14, k=3, d=3):
    """Stochastic RSI via pandas-ta-classic. Returns K line."""
    if len(df) < rsi_length + length:
        return pd.Series(0, index=df.index)
    result = ta.stochrsi(df['close'], length=length, rsi_length=rsi_length, k=k, d=d, mamode="sma")
    if result is None:
        return pd.Series(0, index=df.index)
    k_col = result.columns[0]
    return result[k_col].fillna(0)


def calculate_rsi(df, length=14):
    """RSI via pandas-ta-classic."""
    if len(df) < length:
        return pd.Series(50, index=df.index)
    return ta.rsi(df['close'], length=length)


def calculate_bb_width(df, length=20, std_dev=2):
    """Bollinger Band Width. Manual from BBL/BBM/BBU (library BBB is 100x)."""
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.bbands(df['close'], length=length, std=std_dev)
    if result is None:
        return pd.Series(0, index=df.index)
    cols = result.columns
    lower = result[cols[0]]
    mid = result[cols[1]]
    upper = result[cols[2]]
    mid_safe = mid.replace(0, np.nan)
    bb_width = (upper - lower) / mid_safe
    return bb_width.fillna(0)


def calculate_smi(df, length=10, smooth=3):
    """BLAU'S Stochastic Momentum Index (NOT Ergodic/TSI). Uses high/low/close."""
    hh = df['high'].rolling(window=length).max()
    ll = df['low'].rolling(window=length).min()
    center = (hh + ll) / 2
    diff = hh - ll
    rdiff = df['close'] - center
    num = rdiff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    den = diff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    smi = (num / (0.5 * den.replace(0, np.nan))) * 100
    return smi.fillna(0)


def calculate_macd(df, fast=12, slow=26, signal=9):
    """MACD via pandas-ta-classic. Returns (line, signal, histogram)."""
    if len(df) < slow + signal:
        empty = pd.Series(0.0, index=df.index)
        return empty, empty, empty
    result = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)
    if result is None:
        empty = pd.Series(0.0, index=df.index)
        return empty, empty, empty
    cols = result.columns
    macd_line = result[cols[0]].fillna(0)
    macd_hist = result[cols[1]].fillna(0)
    signal_line = result[cols[2]].fillna(0)
    return macd_line, signal_line, macd_hist


def calculate_vwap(df):
    """Intra-day VWAP with session resets. Manual implementation (avoids timezone warnings)."""
    curr_df = df.copy()
    curr_df['Date'] = curr_df.index.date
    curr_df['Typical_Price'] = (curr_df['high'] + curr_df['low'] + curr_df['close']) / 3
    curr_df['TP_Vol'] = curr_df['Typical_Price'] * curr_df['volume']
    grouped = curr_df.groupby('Date')
    cum_tp_vol = grouped['TP_Vol'].cumsum()
    cum_vol = grouped['volume'].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap.fillna(curr_df['close'])


def calculate_adx(df, length=14):
    """ADX via pandas-ta-classic."""
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.adx(df['high'], df['low'], df['close'], length=length)
    if result is None:
        return pd.Series(0, index=df.index)
    adx_col = result.columns[0]
    return result[adx_col].fillna(0)


def calculate_obv(df):
    """OBV via pandas-ta-classic."""
    return ta.obv(df['close'], df['volume'])


def calculate_atr(df, length=14):
    """ATR via pandas-ta-classic."""
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.atr(df['high'], df['low'], df['close'], length=length)
    if result is None:
        return pd.Series(0, index=df.index)
    return result.fillna(0)


def calculate_ema_slope(df, length=21, lookback=1):
    """EMA slope (difference over lookback bars)."""
    ema = calculate_ema(df, length)
    return ema.diff(lookback).fillna(0)


def calculate_supertrend(df, length=10, multiplier=3):
    """Supertrend via pandas-ta-classic. Returns (trend, direction)."""
    if len(df) < length:
        empty = pd.Series(0.0, index=df.index)
        return empty, pd.Series(1, index=df.index)
    result = ta.supertrend(df['high'], df['low'], df['close'], length=length, multiplier=multiplier)
    if result is None:
        empty = pd.Series(0.0, index=df.index)
        return empty, pd.Series(1, index=df.index)
    cols = result.columns
    trend = result[cols[0]].fillna(0)
    direction = result[cols[1]].fillna(1)
    return trend, direction


def calculate_obv_slope(df, lookback=3):
    """OBV slope over lookback bars."""
    obv = calculate_obv(df)
    return obv.diff(lookback).fillna(0)


def calculate_rsi_slope(df, rsi_length=14, lookback=3):
    """RSI momentum direction."""
    rsi = calculate_rsi(df, rsi_length)
    return rsi.diff(lookback).fillna(0)


def calculate_macd_hist_slope(df, fast=12, slow=26, signal=9, lookback=3):
    """MACD histogram slope (leading momentum indicator)."""
    _, _, hist = calculate_macd(df, fast=fast, slow=slow, signal=signal)
    return hist.diff(lookback).fillna(0)


def calculate_distance_from_ema(df, length):
    """Percentage distance of close from EMA."""
    ema = calculate_ema(df, length)
    ema_safe = ema.replace(0, np.nan)
    distance_pct = ((df['close'] - ema) / ema_safe) * 100
    return distance_pct.fillna(0)


def calculate_rvol(df, lookback=20):
    """Relative Volume: current volume / rolling average."""
    if len(df) < lookback:
        return pd.Series(1.0, index=df.index)
    avg_vol = df['volume'].rolling(window=lookback).mean()
    avg_vol_safe = avg_vol.replace(0, np.nan)
    rvol = df['volume'] / avg_vol_safe
    return rvol.fillna(1.0)


def calculate_supertrend_duration(df, length=10, multiplier=3):
    """Consecutive bars Supertrend has been bullish."""
    _, st_dir = calculate_supertrend(df, length, multiplier)
    duration = pd.Series(0, index=df.index)
    count = 0
    for i in range(len(df)):
        if st_dir.iloc[i] == 1:
            count += 1
        else:
            count = 0
        duration.iloc[i] = count
    return duration


def calculate_ema_crossovers(df, emas):
    """Detect EMA 13x34 and 34x89 crossovers with recency tracking."""
    ema_13 = emas[13]
    ema_34 = emas[34]
    ema_89 = emas[89]

    ema_13x34 = pd.DataFrame({'bull_bars': np.nan, 'bear_bars': np.nan}, index=df.index)
    bull_count = 0
    bear_count = 0
    for i in range(len(df)):
        if ema_13.iloc[i] > ema_34.iloc[i]:
            bull_count += 1
            bear_count = 0
        elif ema_13.iloc[i] < ema_34.iloc[i]:
            bear_count += 1
            bull_count = 0
        if bull_count > 0:
            ema_13x34.iloc[i, ema_13x34.columns.get_loc('bull_bars')] = bull_count
        if bear_count > 0:
            ema_13x34.iloc[i, ema_13x34.columns.get_loc('bear_bars')] = bear_count

    ema_34x89 = pd.DataFrame({'bull_bars': np.nan, 'bear_bars': np.nan}, index=df.index)
    bull_count = 0
    bear_count = 0
    for i in range(len(df)):
        if ema_34.iloc[i] > ema_89.iloc[i]:
            bull_count += 1
            bear_count = 0
        elif ema_34.iloc[i] < ema_89.iloc[i]:
            bear_count += 1
            bull_count = 0
        if bull_count > 0:
            ema_34x89.iloc[i, ema_34x89.columns.get_loc('bull_bars')] = bull_count
        if bear_count > 0:
            ema_34x89.iloc[i, ema_34x89.columns.get_loc('bear_bars')] = bear_count

    result = {}
    for label, df_cross in [('13x34', ema_13x34), ('34x89', ema_34x89)]:
        result[f'{label}_bull_bars'] = df_cross['bull_bars']
        result[f'{label}_bear_bars'] = df_cross['bear_bars']
    return result


def calculate_indicators_batch(df, ema_lengths=None, stoch_rsi_params=None,
                                smi_params=None, macd_params=None):
    """Batch-calculate using pandas-ta-classic Strategy."""
    if ema_lengths is None:
        ema_lengths = [5, 9, 13, 21, 34, 50, 89, 200]
    if stoch_rsi_params is None:
        stoch_rsi_params = {"length": 14, "rsi_length": 14, "k": 3, "d": 3}
    if macd_params is None:
        macd_params = {"fast": 12, "slow": 26, "signal": 9}

    ta_list = []
    for length in ema_lengths:
        ta_list.append({"kind": "ema", "length": length, "sma": False})
    ta_list.append({"kind": "rsi"})
    ta_list.append({"kind": "macd", "fast": macd_params["fast"], "slow": macd_params["slow"], "signal": macd_params["signal"]})
    ta_list.append({"kind": "bbands", "length": 20, "std": 2})
    ta_list.append({"kind": "adx"})
    ta_list.append({"kind": "atr"})
    ta_list.append({"kind": "obv"})
    ta_list.append({"kind": "supertrend", "length": 10, "multiplier": 3})

    strategy = ta.Strategy(name="NSE_Scanner", ta=ta_list)
    df.ta.strategy(strategy, append=True)

    results = {}
    for length in ema_lengths:
        col = f"EMA_{length}"
        if col in df.columns:
            results[f"ema_{length}"] = df[col].fillna(0)
    if "RSI_14" in df.columns:
        results["rsi"] = df["RSI_14"]
    macd_cols = [c for c in df.columns if c.startswith("MACD_") and not c.startswith("MACDh") and not c.startswith("MACDs")]
    macdh_cols = [c for c in df.columns if c.startswith("MACDh_")]
    macds_cols = [c for c in df.columns if c.startswith("MACDs_")]
    if macd_cols: results["macd_line"] = df[macd_cols[0]].fillna(0)
    if macdh_cols: results["macd_hist"] = df[macdh_cols[0]].fillna(0)
    if macds_cols: results["signal_line"] = df[macds_cols[0]].fillna(0)
    adx_cols = [c for c in df.columns if c.startswith("ADX_")]
    if adx_cols: results["adx"] = df[adx_cols[0]].fillna(0)
    atr_cols = [c for c in df.columns if c.startswith("ATR")]
    if atr_cols: results["atr"] = df[atr_cols[0]]
    if "OBV" in df.columns: results["obv"] = df["OBV"]
    st_cols = [c for c in df.columns if c.startswith("SUPERT_") and not c.startswith("SUPERTd") and not c.startswith("SUPERTl") and not c.startswith("SUPERTs")]
    std_cols = [c for c in df.columns if c.startswith("SUPERTd_")]
    if st_cols: results["supertrend"] = df[st_cols[0]].fillna(0)
    if std_cols: results["st_dir"] = df[std_cols[0]].fillna(1)
    results["stoch_rsi_k"] = calculate_stoch_rsi(df, **stoch_rsi_params)
    if smi_params is None:
        smi_params = {"length": 10, "smooth": 3}
    results["smi"] = calculate_smi(df, **smi_params)
    results["vwap"] = calculate_vwap(df)
    return results
```

---

## STEP 6: data_loader.py — EXACT COPY

```python
import pandas as pd
import requests
import io
import pytz
import logging
import os
import time
import hashlib
import pickle
import json
import urllib.request
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from auth_handler import get_fyers_client
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

# Symbol aliases for renamed stocks
SYMBOL_ALIASES = {"ZOMATO": "ETERNAL"}

# Rate limiter
_rate_lock = threading.Lock()
_last_request_time = 0.0
RATE_LIMIT_INTERVAL = 0.25
_rate_limit_backoff_until = 0.0

def _rate_limit_wait():
    global _last_request_time, _rate_limit_backoff_until
    with _rate_lock:
        now = time.time()
        if now < _rate_limit_backoff_until:
            time.sleep(_rate_limit_backoff_until - now)
            now = time.time()
        elapsed = now - _last_request_time
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        _last_request_time = time.time()

def _global_rate_limit_backoff(seconds=5):
    global _rate_limit_backoff_until
    with _rate_lock:
        _rate_limit_backoff_until = max(_rate_limit_backoff_until, time.time() + seconds)

# OHLCV Cache
def _get_ohlcv_cache_key(symbol, resolution, range_from, range_to):
    return hashlib.md5(f"{symbol}_{resolution}_{range_from}_{range_to}".encode()).hexdigest()

def _get_ohlcv_cache(symbol, resolution, range_from, range_to):
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "ohlcv")
    os.makedirs(cache_dir, exist_ok=True)
    now = datetime.now()
    if 9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 30):
        max_age_seconds = 300
    else:
        max_age_seconds = 3600
    key = _get_ohlcv_cache_key(symbol, resolution, range_from, range_to)
    path = os.path.join(cache_dir, f"{key}.pickle")
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < max_age_seconds:
            try:
                with open(path, 'rb') as f:
                    return pickle.load(f)
            except: pass
    return None

def _set_ohlcv_cache(symbol, resolution, range_from, range_to, df):
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "ohlcv")
    os.makedirs(cache_dir, exist_ok=True)
    key = _get_ohlcv_cache_key(symbol, resolution, range_from, range_to)
    path = os.path.join(cache_dir, f"{key}.pickle")
    with open(path, 'wb') as f:
        pickle.dump(df, f)

# Symbol functions
INDEX_SLUGS = {
    "NIFTY 50": "nifty50", "NIFTY BANK": "niftybank", "NIFTY FINANCIAL SERVICES": "niftyfin",
    "NIFTY IT": "niftyit", "NIFTY PHARMA": "niftypharma", "NIFTY AUTO": "niftyauto",
    "NIFTY ENERGY": "niftyenergy", "NIFTY FMCG": "niftyfmcg", "NIFTY MEDIA": "niftymedia",
    "NIFTY METAL": "niftymetal", "NIFTY PSU BANK": "niftypsubank", "NIFTY REALTY": "niftyrealty",
    "NIFTY PRIVATE BANK": "niftypvtbank", "NIFTY COMMODITIES": "niftycommodities",
    "NIFTY CONSUMPTION": "niftycons", "NIFTY INFRASTRUCTURE": "niftyinfra",
    "NIFTY MNC": "niftymnc", "NIFTY OIL & GAS": "niftyoilgas", "NIFTY PSE": "niftypse",
    "NIFTY SERVICES SECTOR": "niftyserv", "NIFTY TOTAL MARKET": "niftytotal",
}

def get_nifty50_symbols():
    url = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
    try:
        df = pd.read_csv(io.StringIO(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).text))
        symbols = [f"NSE:{symbol.strip()}-EQ" for symbol in df['Symbol']]
        return symbols
    except Exception as e:
        logger.error(f"Error fetching Nifty 50: {e}")
        return []

def get_nifty200_symbols():
    url = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    try:
        df = pd.read_csv(io.StringIO(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).text))
        symbols = [f"NSE:{symbol.strip()}-EQ" for symbol in df['Symbol']]
        return symbols
    except:
        return get_nifty50_symbols()

def get_nifty500_symbols():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        df = pd.read_csv(io.StringIO(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).text))
        symbols = [f"NSE:{symbol.strip()}-EQ" for symbol in df['Symbol']]
        return symbols
    except:
        return get_nifty200_symbols()

def get_index_constituents(index_name):
    slug = INDEX_SLUGS.get(index_name)
    if slug:
        url = f"https://archives.nseindia.com/content/indices/ind_{slug}list.csv"
        try:
            df = pd.read_csv(io.StringIO(requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).text))
            return [f"NSE:{symbol.strip()}-EQ" for symbol in df['Symbol']]
        except: pass
    if "50" in index_name: return get_nifty50_symbols()
    if "200" in index_name: return get_nifty200_symbols()
    return get_nifty500_symbols()

def get_all_indices_dict():
    return {**INDEX_SLUGS, "NIFTY 50": "nifty50", "NIFTY 100": "nifty100", "NIFTY 200": "nifty200", "NIFTY 500": "nifty500"}

def normalize_symbol(symbol):
    symbol = symbol.upper().replace(".NS", "").replace(".BO", "")
    if ":" in symbol: return symbol
    return f"NSE:{symbol}-EQ"

def fyers_to_yfinance(fyers_symbol):
    sym = fyers_symbol.upper()
    for old, new in SYMBOL_ALIASES.items():
        if old in sym: sym = sym.replace(old, new)
    if "NIFTY50" in sym: return "^NSEI"
    if "NIFTYBANK" in sym: return "^NSEBANK"
    if ":" in sym: sym = sym.split(":")[1]
    sym = sym.replace("-EQ", "").replace("-INDEX", "")
    return f"{sym}.NS"

# Yahoo Finance Direct API
_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_YF_TIMEOUT = 15

def _yf_fetch_chart(yf_symbol, interval='1h', range_str='60d'):
    url = f"{_YF_BASE}/{yf_symbol}?interval={interval}&range={range_str}"
    req = urllib.request.Request(url, headers={"User-Agent": _YF_UA})
    try:
        with urllib.request.urlopen(req, timeout=_YF_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["chart"]["result"][0]
    except Exception as e:
        logger.debug(f"Yahoo Finance API error for {yf_symbol}: {e}")
        return None

def fetch_data_yfinance(symbol, interval='1h', period='60d'):
    """Fetch via Yahoo Finance direct API."""
    try:
        yf_symbol = fyers_to_yfinance(symbol)
        interval_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '60m': '60m', '1h': '1h', '1d': '1d', 'D': '1d', 'W': '1wk', 'M': '1mo'}
        yf_interval = interval_map.get(interval, '1h')
        if yf_interval == '1m': range_str = '5d'
        elif yf_interval in ['5m', '15m', '30m', '60m', '1h']: range_str = '60d'
        else: range_str = '2y'
        chart_result = _yf_fetch_chart(yf_symbol, interval=yf_interval, range_str=range_str)
        if chart_result is None: return pd.DataFrame()
        timestamps = chart_result.get("timestamp", [])
        indicators = chart_result.get("indicators", {}).get("quote", [{}])[0]
        if not timestamps: return pd.DataFrame()
        df = pd.DataFrame({'open': indicators.get('open', []), 'high': indicators.get('high', []), 'low': indicators.get('low', []), 'close': indicators.get('close', []), 'volume': indicators.get('volume', [])})
        df.index = pd.to_datetime(timestamps, unit='s')
        df.index = df.index.tz_localize('UTC').tz_convert(IST)
        df = df.dropna(subset=['close'])
        if df.empty: return pd.DataFrame()
        for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
        df['volume'] = df['volume'].fillna(0).astype(int)
        return df
    except Exception as e:
        logger.debug(f"Yahoo Finance error for {symbol}: {e}")
        return pd.DataFrame()

def fetch_data_yf_lib(symbol, interval='1h', period='60d'):
    """Fetch via yfinance library."""
    try:
        yf_symbol = fyers_to_yfinance(symbol)
        interval_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '60m': '60m', '1h': '1h', '1d': '1d', 'D': '1d', 'W': '1wk', 'M': '1mo'}
        yf_interval = interval_map.get(interval, '1h')
        if yf_interval == '1m': period = '5d'
        elif yf_interval in ['5m', '15m', '30m', '60m', '1h']: period = '60d'
        else: period = '2y'
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=yf_interval)
        if df.empty: return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']].copy()
        if df.index.tz is not None:
            if str(df.index.tz) != 'Asia/Kolkata': df.index = df.index.tz_convert(IST)
        else:
            df.index = df.index.tz_localize('UTC').tz_convert(IST)
        return df
    except Exception as e:
        logger.debug(f"yfinance error for {symbol}: {e}")
        return pd.DataFrame()

# Data source routing
_DATA_SOURCE_MAP = {
    "auto": "auto", "fyers": "fyers", "fyers api only": "fyers",
    "yahoo": "yahoo", "yahoo finance direct api": "yahoo",
    "yfinance": "yfinance", "yfinance library": "yfinance",
}
_active_data_source = "auto"

def set_data_source(source):
    global _active_data_source
    _active_data_source = _DATA_SOURCE_MAP.get(source.lower(), "auto")
    logger.info(f"📡 Data source set to: {_active_data_source}")

def get_data_source():
    return _active_data_source

# Fyers client
_tls = threading.local()

def _get_thread_fyers():
    if not hasattr(_tls, 'fyers') or _tls.fyers is None:
        _tls.fyers = get_fyers_client()
    return _tls.fyers

# Main fetch function
def fetch_data(symbol, period='1y', interval='1d', retries=2, timeout=10, data_source=None):
    symbol = normalize_symbol(symbol)
    ds = data_source or _active_data_source
    ds = _DATA_SOURCE_MAP.get(ds.lower() if ds else "auto", "auto")

    if ds == "yahoo":
        df = fetch_data_yfinance(symbol, interval=interval)
        if not df.empty:
            res_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60', '1h': '60', '1d': 'D'}
            resolution = res_map.get(interval, 'D')
            range_to = datetime.now().strftime("%Y-%m-%d")
            range_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
            _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
            return df
        return pd.DataFrame()

    if ds == "yfinance":
        df = fetch_data_yf_lib(symbol, interval=interval)
        if not df.empty:
            res_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60', '1h': '60', '1d': 'D'}
            resolution = res_map.get(interval, 'D')
            range_to = datetime.now().strftime("%Y-%m-%d")
            range_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
            _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
            return df
        return pd.DataFrame()

    # Fyers path
    res_map = {'1m': '1', '2m': '2', '3m': '3', '5m': '5', '10m': '10', '15m': '15', '20m': '20', '30m': '30', '60m': '60', '1h': '60', '1d': 'D', '1D': 'D', 'W': 'W', 'M': 'M'}
    resolution = res_map.get(interval, 'D')

    now = datetime.now()
    range_to = now.strftime("%Y-%m-%d")
    bars_per_day_map = {'1m': 375, '5m': 75, '15m': 33, '30m': 17, '60m': 7, '1h': 7, '1d': 1, '1D': 1, 'D': 1}
    min_bars_needed = 300

    if interval == '1m': days = 5
    elif interval in ['1d', '1D', 'D', 'W', 'M']: days = 365
    else:
        bars_per_day = bars_per_day_map.get(interval, 7)
        days = max(30, (min_bars_needed // bars_per_day) + 30)
    range_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    cached_df = _get_ohlcv_cache(symbol, resolution, range_from, range_to)
    if cached_df is not None: return cached_df

    _rate_limit_wait()

    is_index = "INDEX" in symbol or symbol.startswith("NSE:NIFTY")
    data = {"symbol": symbol, "resolution": resolution, "date_format": "1", "range_from": range_from, "range_to": range_to, "cont_flag": "0" if is_index else "1"}

    for attempt in range(retries):
        try:
            fyers = _get_thread_fyers()
            if not fyers: return pd.DataFrame()
            response = fyers.history(data=data)
            if response.get("s") == "ok":
                candles = response.get("candles", [])
                if not candles: return pd.DataFrame()
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('timestamp', inplace=True)
                if df.index.tz is None: df.index = df.index.tz_localize('UTC').tz_convert(IST)
                else: df.index = df.index.tz_convert(IST)
                _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
                return df
            else:
                msg = response.get("message", "Unknown error")
                if "request limit reached" in msg.lower() or "too many" in msg.lower():
                    _global_rate_limit_backoff(3 * (attempt + 1))
                    time.sleep(3 * (attempt + 1))
                elif "token" in msg.lower() or "expired" in msg.lower(): return pd.DataFrame()
                if attempt < retries - 1: time.sleep(1.0)
        except Exception as e:
            if attempt < retries - 1: time.sleep(0.3)

    # Fallback to Yahoo Finance
    logger.info(f"Fyers failed for {symbol}, trying yfinance fallback...")
    df = fetch_data_yfinance(symbol, interval=interval)
    if not df.empty:
        logger.info(f"yfinance fallback OK: {symbol} ({len(df)} bars)")
        _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
        return df
    return pd.DataFrame()

# Batch fetch functions
def fetch_data_batch_fast(symbols, interval='1h', data_source='yahoo', max_workers=20):
    """Fast parallel batch for non-rate-limited sources."""
    t0 = time.time()
    results = {}
    total = len(symbols)
    logger.info(f"⚡ Fast batch fetch: {total} symbols ({data_source}, {max_workers} workers)")

    def _fetch_one(sym):
        df = fetch_data(sym, interval=interval, data_source=data_source)
        return sym, df

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            try:
                sym, df = future.result(timeout=30)
                if df is not None and not df.empty: results[sym] = df
            except: pass
    elapsed = time.time() - t0
    logger.info(f"⚡ Fast batch complete: {len(results)}/{total} in {elapsed:.1f}s")
    return results

def fetch_data_batch(symbols, interval='1h', max_workers=2):
    """Batch fetch — routes to fast or rate-limited based on data source."""
    ds = _active_data_source
    if ds in ('yahoo', 'yfinance'):
        return fetch_data_batch_fast(symbols, interval=interval, data_source=ds, max_workers=20)

    # Fyers rate-limited batch
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    total = len(symbols)
    batch_size = 100
    for batch_start in range(0, total, batch_size):
        batch = symbols[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(f"  Batch {batch_num}/{total_batches}: fetching {len(batch)} symbols...")
        def _fetch_one(sym):
            df = fetch_data(sym, interval=interval)
            return sym, df
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, sym): sym for sym in batch}
            for future in as_completed(futures):
                try:
                    sym, df = future.result(timeout=60)
                    if df is not None and not df.empty: results[sym] = df
                except: pass
        if batch_start + batch_size < total: time.sleep(1)
    logger.info(f"Batch fetch complete: {len(results)}/{total} symbols have data")
    return results

def clear_ohlcv_cache():
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "ohlcv")
    if os.path.exists(cache_dir):
        count = 0
        for f in os.listdir(cache_dir):
            os.remove(os.path.join(cache_dir, f))
            count += 1
        logger.info(f"Cleared {count} OHLCV cache files")
```

---

## STEP 7: scanner.py — EXACT COPY

```python
import os
import pandas as pd
import numpy as np
import indicators
import data_loader
import config
import concurrent.futures
import pytz
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')


def calc_ignition_score(c, pos, df, close, rsi, macd_hist, stoch_rsi_k, emas,
                        ema9_slope, st_dir, obv_slope, dist_ema21, rvol_val,
                        ema_crosses=None):
    sc = config.SCORE_CONFIG
    score = 0
    mh = macd_hist.iloc[pos]
    mh_prev = macd_hist.iloc[pos - 1] if pos > 0 else mh
    mh_prev2 = macd_hist.iloc[pos - 2] if pos > 1 else mh_prev
    if mh_prev <= 0 < mh: score += 30
    elif mh > 0 and mh > mh_prev > mh_prev2: score += 20
    elif mh > mh_prev: score += 10
    elif mh_prev < 0 and mh > mh_prev: score += 5
    r = rsi.iloc[pos]
    r_prev = rsi.iloc[pos - 1] if pos > 0 else r
    if r_prev < 45 <= r: score += 25
    elif r_prev < 50 <= r: score += 20
    elif 35 < r < 55 and r > r_prev: score += 15
    elif 40 < r < 60 and r > r_prev: score += 10
    e9 = emas[9].iloc[pos]
    e9_prev = emas[9].iloc[pos - 1] if pos > 0 else e9
    c_prev = close.iloc[pos - 1] if pos > 0 else c
    if c > e9 and c_prev <= e9_prev: score += 20
    elif c > e9 and ema9_slope.iloc[pos] > 0: score += 10
    elif c > e9 and c_prev > emas[9].iloc[pos - 1]: score += 5
    rv = rvol_val.iloc[pos]
    rv_prev = rvol_val.iloc[pos - 1] if pos > 0 else rv
    if rv > 1.5 and rv > rv_prev: score += 15
    elif rv > 1.2 and rv > rv_prev: score += 10
    elif rv > 1.0: score += 5
    sd = st_dir.iloc[pos]
    sd_prev = st_dir.iloc[pos - 1] if pos > 0 else sd
    if sd_prev == -1 and sd == 1: score += 15
    elif sd == 1: score += 5
    obv_s = obv_slope.iloc[pos]
    if obv_s > 0: score += 10
    if ema_crosses:
        bull_13x34 = ema_crosses['13x34_bull_bars'].iloc[pos]
        if not np.isnan(bull_13x34):
            if bull_13x34 <= 1: score += 20
            elif bull_13x34 <= 3: score += 15
            elif bull_13x34 <= 5: score += 8
    d21 = dist_ema21.iloc[pos]
    if 0 <= d21 <= 3.0: score += 8
    elif -1.0 <= d21 < 0: score += 5
    if r > 80: score -= 15
    if d21 > 8.0: score -= 20
    if stoch_rsi_k.iloc[pos] > 95: score -= 10
    return max(0, min(100, score))


def calc_intraday_score(c, pos, df, close, rsi, vwap, emas, adx, rvol_val,
                        dist_ema21, stoch_rsi_k, day_open_price, is_intraday,
                        orb30_high, ema_crosses=None):
    sc = config.SCORE_CONFIG
    score = 0
    if is_intraday:
        vw = vwap.iloc[pos]
        if vw > 0:
            vw_distance = ((c / vw) - 1) * 100
            if 0 < vw_distance <= 1: score += 10
            elif 1 < vw_distance <= 2: score += 15
            elif 2 < vw_distance <= 3: score += 20
            elif 3 < vw_distance <= 4: score += 10
            elif vw_distance < 0: score -= 10
    if orb30_high > 0 and c > orb30_high:
        score += 20
    rv = rvol_val.iloc[pos]
    if rv >= sc["RVOL_INSTITUTIONAL"]: score += 15
    elif rv >= sc["RVOL_ELEVATED"]: score += 10
    e5, e9, e21 = emas[5].iloc[pos], emas[9].iloc[pos], emas[21].iloc[pos]
    if e5 > e9 > e21:
        prox = abs(c - e5) / e5 * 100
        if prox <= 1.5: score += 15
        elif prox <= 3: score += 10
        elif prox <= 5: score += 8
    elif e5 > e21 and e9 < e21: score += 3
    if ema_crosses:
        bull_13x34 = ema_crosses['13x34_bull_bars'].iloc[pos]
        if not np.isnan(bull_13x34) and bull_13x34 <= 3: score += 10
    a = adx.iloc[pos]
    a_prev = adx.iloc[pos - 1] if pos > 0 else a
    if a > 20 and a > a_prev: score += 10
    elif a > 25: score += 5
    r = rsi.iloc[pos]
    if sc["RSI_INTRADAY_SWEET_LOW"] <= r <= sc["RSI_INTRADAY_SWEET_HIGH"]: score += 10
    elif 50 <= r < sc["RSI_INTRADAY_SWEET_LOW"]: score += 5
    if is_intraday and day_open_price > 0:
        day_change = ((c / day_open_price) - 1) * 100
        if 0.5 <= day_change <= 2: score += 10
        elif 0.1 <= day_change <= 3: score += 5
    if r > sc["RSI_EXHAUSTION"]: score -= 15
    if dist_ema21.iloc[pos] > 8: score -= 20
    if stoch_rsi_k.iloc[pos] > 95: score -= 10
    return max(0, min(100, score))


def calc_swing_score(c, pos, df, close, rsi, emas, adx, macd_hist,
                     bb_width, dist_ema21, obv_slope, rvol_val,
                     st_duration, relative_strength, ema_crosses=None):
    sc = config.SCORE_CONFIG
    score = 0
    bbw = bb_width.iloc[pos]
    bbw_prev = bb_width.iloc[pos - 1] if pos > 0 else bbw
    if bbw <= sc["BBW_SQUEEZE_THRESHOLD"]: score += 20
    elif bbw <= 0.06 and bbw_prev > bbw: score += 15
    elif bbw <= 0.08: score += 10
    rs = relative_strength.iloc[pos] if hasattr(relative_strength, 'iloc') else relative_strength
    if rs >= 2: score += 20
    elif rs >= 1: score += 15
    elif rs >= 0: score += 10
    elif rs >= -2: score += 5
    e = emas
    if e[9].iloc[pos] > e[21].iloc[pos] > e[50].iloc[pos]:
        if e[50].iloc[pos] > e[200].iloc[pos]: score += 15
        else: score += 10
    elif e[21].iloc[pos] > e[50].iloc[pos]: score += 5
    if ema_crosses:
        bull_34x89 = ema_crosses['34x89_bull_bars'].iloc[pos]
        if not np.isnan(bull_34x89):
            if bull_34x89 <= 1: score += 12
            elif bull_34x89 <= 3: score += 8
            elif bull_34x89 <= 5: score += 4
    mh = macd_hist.iloc[pos]
    mh_prev = macd_hist.iloc[pos - 1] if pos > 0 else mh
    mh_prev2 = macd_hist.iloc[pos - 2] if pos > 1 else mh_prev
    if mh > 0 and mh > mh_prev > mh_prev2: score += 15
    elif mh > mh_prev: score += 5
    a = adx.iloc[pos]
    a_prev = adx.iloc[pos - 1] if pos > 0 else a
    if a > 20 and a > a_prev: score += 10
    elif a > 25: score += 5
    if obv_slope.iloc[pos] > 0 and rvol_val.iloc[pos] > 1.0: score += 10
    elif rvol_val.iloc[pos] > 1.2: score += 5
    sd = st_duration.iloc[pos]
    if sd >= 5: score += 10
    elif sd >= 3: score += 7
    elif sd >= 1: score += 3
    if rsi.iloc[pos] > 80: score -= 20
    if dist_ema21.iloc[pos] > 8: score -= 15
    if bbw > sc["BBW_EXPANDED_THRESHOLD"]: score -= 10
    return max(0, min(100, score))


def calc_decay_penalty(pos, df, close, rsi, macd_hist, stoch_rsi_k, emas,
                       ema9_slope, dist_ema21, rsi_slope, macd_hist_slope,
                       ema_crosses=None):
    penalty = 0
    details = []
    r = rsi.iloc[pos]
    r_prev3 = rsi.iloc[pos - 3] if pos >= 3 else r
    if r_prev3 > 75 and r < r_prev3 - 5 and rsi_slope.iloc[pos] < 0:
        p = min(20, (r_prev3 - r) * 2)
        penalty += p
        details.append(f"RSI fade ({r:.0f}←{r_prev3:.0f})")
    sk = stoch_rsi_k.iloc[pos]
    sk_prev3 = stoch_rsi_k.iloc[pos - 3] if pos >= 3 else sk
    if sk_prev3 > 90 and sk < sk_prev3 - 10:
        penalty += 15
        details.append("StochRSI topped")
    mh = macd_hist.iloc[pos]
    mh_prev3 = macd_hist.iloc[pos - 3] if pos >= 3 else mh
    if mh_prev3 > 0 and mh < mh_prev3:
        if mh < 0: penalty += 15
        else: penalty += 10
        details.append("MACD hist shrinking")
    c_prev = close.iloc[pos - 1] if pos > 0 else close.iloc[pos]
    e9_prev = emas[9].iloc[pos - 1] if pos > 0 else emas[9].iloc[pos]
    if c_prev > e9_prev and close.iloc[pos] < emas[9].iloc[pos] and ema9_slope.iloc[pos] < 0:
        penalty += 10
        details.append("Price broke EMA9")
    if dist_ema21.iloc[pos - 1] > 3 and pos >= 5:
        red_count = sum(1 for i in range(5) if close.iloc[pos - i] < close.iloc[pos - i - 1])
        if red_count >= 3: penalty += 8
    if ema_crosses:
        bear_13x34 = ema_crosses['13x34_bear_bars'].iloc[pos]
        if not np.isnan(bear_13x34) and bear_13x34 <= 3:
            penalty += 15
            details.append("EMA 13x34 bearish cross")
    if penalty >= 30: flag = "DISTRIBUTION"
    elif penalty >= 15: flag = "FADING"
    else: flag = ""
    return penalty, flag, "; ".join(details)


def check_conditions(df, symbol, nifty_df=None):
    if df.empty or len(df) < 50: return []
    df = df[~df.index.duplicated(keep='last')]
    if nifty_df is not None and not nifty_df.empty:
        nifty_df = nifty_df[~nifty_df.index.duplicated(keep='last')]
    close = df['close']
    volume = df['volume']
    sc = config.SCORE_CONFIG
    strat = config.STRATEGY_CONFIG

    emas = {length: indicators.calculate_ema(df, length) for length in [5, 9, 13, 21, 34, 50, 89, 200]}
    stoch_rsi_k = indicators.calculate_stoch_rsi(df, **strat.get("STOCH_RSI", {}))
    smi = indicators.calculate_smi(df, **strat.get("SMI", {}))
    rsi = indicators.calculate_rsi(df)
    macd_line, signal_line, macd_hist = indicators.calculate_macd(df, **strat.get("MACD", {}))
    bb_width = indicators.calculate_bb_width(df)
    vwap = indicators.calculate_vwap(df)
    adx = indicators.calculate_adx(df)
    obv_slope = indicators.calculate_obv_slope(df)
    ema9_slope = indicators.calculate_ema_slope(df, length=9)
    supertrend, st_dir = indicators.calculate_supertrend(df)
    dist_ema21 = indicators.calculate_distance_from_ema(df, 21)
    rvol_val = indicators.calculate_rvol(df)
    ema_crosses = indicators.calculate_ema_crossovers(df, emas)
    st_duration = indicators.calculate_supertrend_duration(df)
    rsi_slope = indicators.calculate_rsi_slope(df)
    macd_hist_slope = indicators.calculate_macd_hist_slope(df)
    atr = indicators.calculate_atr(df)

    is_intraday = False
    if len(df) > 1:
        time_diff = df.index[-1] - df.index[-2]
        if time_diff < pd.Timedelta(days=1): is_intraday = True

    lookback = min(5, len(df))
    indices_to_check = df.index[-lookback:].tolist()
    avg_vol_20 = volume.rolling(window=20).mean()

    nifty_changes = pd.Series(0, index=df.index)
    if nifty_df is not None and not nifty_df.empty:
        nifty_c = nifty_df['close'].reindex(df.index).ffill()
        nifty_changes = (nifty_c / nifty_c.shift(5) - 1) * 100

    results = []
    for idx in indices_to_check:
        try:
            pos = df.index.get_loc(idx)
            if isinstance(pos, slice): pos = pos.start
            elif isinstance(pos, np.ndarray): pos = int(np.where(pos)[0][0])
            if pos < 5: continue
            c = close.iloc[pos]
            r = rsi.iloc[pos]
            if pd.isna(c) or pd.isna(r): continue

            last_date = idx.date()
            day_data = df[df.index.date == last_date]
            day_open_price = day_data.iloc[0]['open'] if not day_data.empty else df['open'].iloc[pos]
            orb30_high = 0
            if is_intraday:
                try:
                    today_start = idx.replace(hour=9, minute=15, second=0, microsecond=0)
                    today_orb_end = idx.replace(hour=9, minute=45, second=0, microsecond=0)
                    orb_data = df.loc[today_start:today_orb_end]
                    if not orb_data.empty: orb30_high = orb_data['high'].max()
                except: pass

            stock_5_perf = (c / close.iloc[pos - 5] - 1) * 100
            nifty_5_perf = nifty_changes.iloc[pos] if not pd.isna(nifty_changes.iloc[pos]) else 0
            relative_strength = stock_5_perf - nifty_5_perf

            ignition = calc_ignition_score(c, pos, df, close, rsi, macd_hist, stoch_rsi_k, emas, ema9_slope, st_dir, obv_slope, dist_ema21, rvol_val, ema_crosses)
            intraday = calc_intraday_score(c, pos, df, close, rsi, vwap, emas, adx, rvol_val, dist_ema21, stoch_rsi_k, day_open_price, is_intraday, orb30_high, ema_crosses)
            swing = calc_swing_score(c, pos, df, close, rsi, emas, adx, macd_hist, bb_width, dist_ema21, obv_slope, rvol_val, st_duration, relative_strength, ema_crosses)
            decay_penalty, decay_flag, decay_details = calc_decay_penalty(pos, df, close, rsi, macd_hist, stoch_rsi_k, emas, ema9_slope, dist_ema21, rsi_slope, macd_hist_slope, ema_crosses)

            fresh_reversal = (pos >= 1 and macd_hist.iloc[pos] > 0 and macd_hist.iloc[pos - 1] <= 0)
            if decay_penalty > 0 and not fresh_reversal:
                ignition = max(0, ignition - decay_penalty)
                intraday = max(0, intraday - decay_penalty)
                swing = max(0, swing - decay_penalty)

            signal_type = "NEUTRAL"
            if decay_flag: signal_type = decay_flag
            elif intraday >= sc["INTRADAY_THRESHOLD"] and swing >= sc["SWING_THRESHOLD"]:
                signal_type = "🔥⚡ DUAL"
            elif ignition >= 35 and r < 70 and dist_ema21.iloc[pos] < 6:
                signal_type = "🚀 FRESH"
            elif ignition >= sc["IGNITION_THRESHOLD"]: signal_type = "🔥 IGNITION"
            elif intraday >= sc["INTRADAY_THRESHOLD"]: signal_type = "⚡ INTRADAY"
            elif swing >= sc["SWING_THRESHOLD"]: signal_type = "🌊 SWING"
            elif ignition >= 30 or intraday >= 35 or swing >= 35: signal_type = "👀 WATCH"

            pine_ema_ok = (c > emas[5].iloc[pos]) and (c > emas[9].iloc[pos]) and (c > emas[21].iloc[pos])
            pine_stoch_ok = stoch_rsi_k.iloc[pos] > strat.get("STOCH_RSI_K_MIN", 70)
            pine_smi_ok = smi.iloc[pos] > strat.get("SMI_MIN", 30)
            pine_macd_ok = macd_line.iloc[pos] > strat.get("MACD_MIN", 0.75)
            pine_buy_signal = "BUY" if (pine_ema_ok and pine_stoch_ok and pine_smi_ok and pine_macd_ok) else ""

            legacy_score = 0
            if c > emas[5].iloc[pos]: legacy_score += 1
            if c > emas[9].iloc[pos]: legacy_score += 1
            if c > emas[21].iloc[pos]: legacy_score += 1
            if emas[9].iloc[pos] > emas[21].iloc[pos]: legacy_score += 1
            if stoch_rsi_k.iloc[pos] > 70: legacy_score += 1
            if smi.iloc[pos] > 30: legacy_score += 1
            if rsi.iloc[pos] > 60: legacy_score += 1
            if macd_hist.iloc[pos] > 0: legacy_score += 1
            if adx.iloc[pos] > 20: legacy_score += 1
            if rvol_val.iloc[pos] > 1.5: legacy_score += 1

            if atr.iloc[pos] > 0:
                entry_zone = emas[9].iloc[pos]
                stop_loss = round(c - 1.5 * atr.iloc[pos], 2)
                target_1 = round(c + 2 * atr.iloc[pos], 2)
                target_2 = round(c + 3 * atr.iloc[pos], 2)
            else:
                entry_zone = emas[9].iloc[pos]
                stop_loss = round(c * 0.97, 2)
                target_1 = round(c * 1.03, 2)
                target_2 = round(c * 1.05, 2)

            overext_flag = ""
            d21 = dist_ema21.iloc[pos]
            if d21 > 5.0: overext_flag = f"⚠️ OVEREXTENDED +{d21:.1f}%"
            elif d21 < -5.0: overext_flag = f"⚠️ WEAK {d21:.1f}%"

            res = {
                "Stock Name": symbol, "LTP": round(c, 2), "Volume": int(volume.iloc[pos]),
                "Signal Time": idx, "signal_type": signal_type,
                "ignition_score": ignition, "intraday_score": intraday, "swing_score": swing,
                "RSI": round(r, 1), "StochRSI_K": round(stoch_rsi_k.iloc[pos], 1), "SMI": round(smi.iloc[pos], 1),
                "MACD_Hist_Slope": round(macd_hist_slope.iloc[pos], 4),
                "RVOL": round(rvol_val.iloc[pos], 2), "ADX": round(adx.iloc[pos], 1),
                "BBW": round(bb_width.iloc[pos], 4), "Dist_EMA21": round(d21, 2),
                "Rel Strength": round(relative_strength, 2),
                "Overext_Flag": overext_flag,
                "decay_penalty": decay_penalty, "decay_flag": decay_flag, "decay_details": decay_details,
                "Pine Signal": pine_buy_signal, "Legacy_Score": legacy_score,
                "Entry_Zone": entry_zone, "Stop_Loss": stop_loss,
                "Target_1": target_1, "Target_2": target_2,
            }
            for l in [5, 9, 21, 50, 200]:
                if l in emas: res[f"EMA{l}"] = round(emas[l].iloc[pos], 2)
            is_actionable = (
                pine_buy_signal == "BUY" or signal_type == "🚀 FRESH" or signal_type == "🔥⚡ DUAL" or
                signal_type == "👀 WATCH" or ignition >= sc["IGNITION_THRESHOLD"] or
                intraday >= sc["INTRADAY_THRESHOLD"] or swing >= sc["SWING_THRESHOLD"]
            )
            if is_actionable:
                results.append(res)
        except Exception as e:
            logger.warning(f"[{symbol}] Error at {idx}: {type(e).__name__}: {e}")
            continue
    return results


def scan_market(symbols, interval='1h', progress_callback=None):
    t0 = datetime.now()
    total = len(symbols)
    logger.info(f"⚡ Phase 1: Pre-fetching {total} symbols...")
    t1 = time.time() if 'time' in dir() else __import__('time').time()
    import time
    t1 = time.time()
    data_cache = data_loader.fetch_data_batch(symbols, interval=interval, max_workers=2)
    logger.info(f"✅ Phase 1 done: {len(data_cache)}/{total} symbols fetched in {time.time()-t1:.1f}s")

    nifty_df = data_loader.fetch_data("^NSEI", interval=interval)

    logger.info(f"⚡ Phase 2: Computing indicators for {len(data_cache)} symbols...")
    all_results = []
    completed = 0

    def process_symbol(sym):
        df = data_cache.get(sym)
        if df is None or df.empty: return []
        return check_conditions(df, sym, nifty_df=nifty_df)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(process_symbol, sym): sym for sym in symbols if sym in data_cache}
        for future in concurrent.futures.as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except: pass
            completed += 1
            if progress_callback and completed % 50 == 0:
                progress_callback(completed, total)

    elapsed = time.time() - t1
    results_df = pd.DataFrame(all_results)
    if not results_df.empty:
        fresh_count = len(results_df[results_df['signal_type'].str.contains('FRESH', na=False)])
        dual_count = len(results_df[results_df['signal_type'].str.contains('DUAL', na=False)])
        logger.info(f"✅ Scan complete: {len(all_results)} signals from {len(results_df['Stock Name'].unique())} stocks in {elapsed:.1f}s")
        logger.info(f"   FRESH:{fresh_count} | DUAL:{dual_count}")
    else:
        logger.info(f"✅ Scan complete: 0 signals in {elapsed:.1f}s")
    return results_df
```

---

## STEP 8: reporter.py — EXACT COPY

```python
import pandas as pd
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

def _format_stock_line(row, score_key, max_score, show_entry=True):
    name = row['Stock Name']
    ltp = row['LTP']
    score = int(row.get(score_key, 0))
    rsi = row.get('RSI', 0)
    rvol = row.get('RVOL', 0)
    d21 = row.get('Dist_EMA21', 0)
    decay = row.get('decay_flag', '')
    overext = row.get('Overext_Flag', '')
    line = f"👉 *{name}* ₹{ltp} | {score}/{max_score} | RSI:{rsi:.0f} RVOL:{rvol:.1f}x"
    if overext: line += f" | {overext}"
    elif decay: line += f" | {decay}"
    elif d21 > 3: line += f" | Ext:{d21:+.1f}%"
    if show_entry and not decay:
        entry = row.get('Entry_Zone', 0)
        sl = row.get('Stop_Loss', 0)
        t1 = row.get('Target_1', 0)
        t2 = row.get('Target_2', 0)
        if entry and sl:
            line += f"\n   📍 ₹{entry:.0f} SL:₹{sl:.0f} T1:₹{t1:.0f} T2:₹{t2:.0f}"
    return line

def split_list_to_chunks(items, max_chars=3800):
    chunks, current_chunk, current_length = [], [], 0
    for item in items:
        if current_length + len(item) + 1 > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk, current_length = [item], len(item)
        else:
            current_chunk.append(item)
            current_length += len(item) + 1
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

def generate_report(df, universe, timeframe):
    if df.empty: return []
    now_ist = datetime.now(IST)
    now_ist_str = now_ist.strftime('%d-%m-%Y %H:%M:%S')
    total_found = len(df)

    avg_ign = df['ignition_score'].mean()
    avg_intra = df['intraday_score'].mean()
    if avg_ign > 50 and avg_intra > 50: mood = "🚀 *Strong Momentum*"
    elif avg_ign > 40 or avg_intra > 40: mood = "🟢 *Bullish Bias*"
    else: mood = "⚪ *Neutral*"

    df_work = df.copy()
    df_work['_max_score'] = df_work[['ignition_score', 'intraday_score', 'swing_score']].max(axis=1)
    fresh_mask = df_work['signal_type'].str.contains('FRESH', na=False)
    fresh_df = df_work[fresh_mask].sort_values('ignition_score', ascending=False).drop_duplicates(subset='Stock Name')
    other_df = df_work[~fresh_mask].sort_values('Signal Time', ascending=False).drop_duplicates(subset='Stock Name')
    fresh_stocks = set(fresh_df['Stock Name'])
    other_filtered = other_df[~other_df['Stock Name'].isin(fresh_stocks)]
    unique_df = pd.concat([fresh_df, other_filtered]).copy()

    all_chunks = []
    is_decay = unique_df.get('decay_flag', pd.Series('', index=unique_df.index)).str.len() > 0
    clean_df = unique_df[~is_decay]

    # Part 1: Header + Fresh + Dual + Ignition
    p1_lines = [
        f"🚀 *NSE Market Analysis v3.0* | 📊 *{universe}*",
        f"----------------------------------------",
        f"🏁 *MOOD:* _{mood}_",
        f"✅ *Signals:* {total_found} | *TF:* {timeframe} | _{now_ist_str}_",
        f"----------------------------------------",
    ]
    fresh_out = clean_df[clean_df['signal_type'].str.contains('FRESH', na=False)].nlargest(5, 'ignition_score')
    if not fresh_out.empty:
        p1_lines.append(f"🚀 *FRESH SIGNALS — Early Detection (1h)*")
        p1_lines.append(f"_Stocks just starting momentum — NOT overbought_")
        for _, row in fresh_out.iterrows():
            ign = int(row.get('ignition_score', 0))
            name = row['Stock Name']
            ltp = row['LTP']
            rsi_val = row.get('RSI', 0)
            rvol = row.get('RVOL', 0)
            d21 = row.get('Dist_EMA21', 0)
            line = f"👉 *{name}* ₹{ltp} | IGN:{ign} | RSI:{rsi_val:.0f} RVOL:{rvol:.1f}x | EMA21:{d21:+.1f}%"
            if 'Entry_Zone' in row:
                line += f"\n   📍 Entry:₹{row['Entry_Zone']} SL:₹{row['Stop_Loss']} T1:₹{row['Target_1']} T2:₹{row['Target_2']}"
            p1_lines.append(line)
        p1_lines.append(f"----------------------------------------")
    dual_out = clean_df[clean_df['signal_type'].str.contains('DUAL', na=False)].nlargest(5, 'ignition_score')
    if not dual_out.empty:
        p1_lines.append(f"🔥⚡ *DUAL OPPORTUNITIES — Intraday + Swing*")
        for _, row in dual_out.iterrows():
            intra = int(row.get('intraday_score', 0))
            sw = int(row.get('swing_score', 0))
            ign = int(row.get('ignition_score', 0))
            line = f"👉 *{row['Stock Name']}* ₹{row['LTP']} | IGN:{ign} INTRA:{intra} SW:{sw} | RSI:{row.get('RSI',0):.0f} RVOL:{row.get('RVOL',0):.1f}x"
            if 'Entry_Zone' in row:
                line += f"\n   📍 Entry:₹{row['Entry_Zone']} SL:₹{row['Stop_Loss']} T1:₹{row['Target_1']} T2:₹{row['Target_2']}"
            p1_lines.append(line)
        p1_lines.append(f"----------------------------------------")
    ign_out = clean_df[(clean_df['ignition_score'] >= 50) & (clean_df['RVOL'] >= 0.8)].nlargest(5, 'ignition_score')
    if not ign_out.empty:
        p1_lines.append(f"🔥 *IGNITION ALERTS — Trend Birth Detection*")
        for _, row in ign_out.iterrows():
            p1_lines.append(_format_stock_line(row, 'ignition_score', 100, show_entry=True))
        p1_lines.append(f"----------------------------------------")
    all_chunks.extend(split_list_to_chunks(p1_lines, 3800))

    # Part 2: Intraday
    p2_lines = []
    intra_out = clean_df[(clean_df['intraday_score'] >= 55) & (clean_df['RVOL'] >= 0.8)].nlargest(5, 'intraday_score')
    if not intra_out.empty:
        p2_lines.append(f"⚡ *INTRADAY PLAYS — Ride Today's Move*")
        for _, row in intra_out.iterrows():
            p2_lines.append(_format_stock_line(row, 'intraday_score', 100, show_entry=True))
        p2_lines.append(f"----------------------------------------")
    if p2_lines:
        all_chunks.extend(split_list_to_chunks(p2_lines, 3800))

    # Part 3: Swing
    p3_lines = []
    swing_out = clean_df[(clean_df['swing_score'] >= 55) & (clean_df['RVOL'] >= 0.6)].nlargest(5, 'swing_score')
    if not swing_out.empty:
        p3_lines.append(f"🌊 *SWING SETUPS — Multi-Day Builders*")
        for _, row in swing_out.iterrows():
            bbw = row.get('BBW', 0)
            squeeze = " 🌀SQZ" if bbw <= 0.04 else ""
            rs = row.get('Rel Strength', 0)
            line = _format_stock_line(row, 'swing_score', 100, show_entry=True)
            line += f"{squeeze} RS:{rs:+.1f}"
            p3_lines.append(line)
        p3_lines.append(f"----------------------------------------")
    if p3_lines:
        all_chunks.extend(split_list_to_chunks(p3_lines, 3800))

    # Part 4: Decay warnings
    p4_lines = []
    decay_out = unique_df[is_decay].nlargest(5, 'decay_penalty')
    if not decay_out.empty:
        p4_lines.append(f"📉 *FADING / DISTRIBUTION — DO NOT BUY*")
        for _, row in decay_out.iterrows():
            penalty = row.get('decay_penalty', 0)
            details = row.get('decay_details', '')
            line = f"👉 *{row['Stock Name']}* ₹{row['LTP']} | Decay:{penalty} | RSI:{row.get('RSI',0):.0f}"
            if details: line += f" | {details}"
            p4_lines.append(line)
        p4_lines.append(f"----------------------------------------")
    if p4_lines:
        all_chunks.extend(split_list_to_chunks(p4_lines, 3800))

    return all_chunks
```

---

## STEP 9: app.py — EXACT COPY

```python
import streamlit as st
import pandas as pd
import scanner
import data_loader
import config
import reporter
import pytz
import os
import requests
import io
import logging
import indicators
from datetime import datetime, date, timedelta

# Log capture for UI
log_lines = []
class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_lines.append(msg)
log_handler = StreamlitLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
log_handler.setLevel(logging.INFO)
for name in ['scanner', 'data_loader', 'auth_handler']:
    lg = logging.getLogger(name)
    lg.addHandler(log_handler)

st.set_page_config(page_title="NSE Scanner", page_icon="📈", layout="wide")
st.title("🚀 NSE Stock Scanner 2.0")

# Sidebar
st.sidebar.header("⚙️ Scan Configuration")
universe_options = ["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500"]
for idx_name in data_loader.get_all_indices_dict():
    if idx_name not in universe_options: universe_options.append(idx_name)
selected_universe = st.sidebar.selectbox("Stock Universe", universe_options, index=3)
timeframe_options = ["1h", "15m", "5m", "1d"]
selected_timeframe = st.sidebar.selectbox("Timeframe (Interval)", timeframe_options, index=0)
st.sidebar.markdown("---")
st.sidebar.subheader("📡 Data Source")
data_source_options = ["🔄 Auto (Fyers → Yahoo API → yfinance)", "Fyers API Only", "Yahoo Finance Direct API", "yfinance Library"]
selected_data_source = st.sidebar.selectbox("Data Fetch Method", data_source_options, index=0)
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Signal Filter")
filter_options = ["All Signals", "🚀 FRESH (Early Detection)", "🔥⚡ DUAL (Intraday+Swing)", "🔥 IGNITION", "⚡ INTRADAY", "🌊 SWING", "Pine BUY Only", "Exclude Decay"]
signal_filter = st.sidebar.selectbox("Show signals", filter_options, index=0)

if "scan_metadata" not in st.session_state:
    st.session_state.scan_metadata = {"universe": selected_universe, "timeframe": selected_timeframe}
if (selected_universe != st.session_state.scan_metadata["universe"] or selected_timeframe != st.session_state.scan_metadata["timeframe"]):
    st.session_state.results_df = None
    st.session_state.scan_metadata = {"universe": selected_universe, "timeframe": selected_timeframe}

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)

def send_to_telegram(df, universe, timeframe):
    now_ist = datetime.now(pytz.timezone('Asia/Kolkata'))
    timestamp = now_ist.strftime('%d-%m-%Y %H:%M:%S')
    report_parts = reporter.generate_report(df, universe, timeframe)
    if not report_parts: return False
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    doc_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {'document': ('nse2_scan_results.csv', csv_buffer.getvalue())}
    data = {'chat_id': CHAT_ID, 'caption': report_parts[0], 'parse_mode': 'Markdown'}
    try:
        response = requests.post(doc_url, files=files, data=data, timeout=20)
        if response.status_code != 200: return False
        msg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for part in report_parts[1:]:
            requests.post(msg_url, json={"chat_id": CHAT_ID, "text": part, "parse_mode": "Markdown"}, timeout=20)
        return True
    except: return False

def show_fyers_auth_ui():
    st.markdown("---")
    st.error("🔑 **Fyers Authentication Required**")
    st.info("Fyers API access tokens expire daily at 11:59 PM. Please refresh your session.")
    login_url = "#"
    try:
        from auth_handler import _handler
        login_url = _handler.get_login_url()
    except: pass
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"### Steps to Refresh:\n1. **[👉 Click here to Login to Fyers]({login_url})**\n2. Log in and click **Authorize**.\n3. You will be redirected to your app URL.\n4. **Copy the `auth_code`** from the redirect URL.\n5. Paste it into the box on the right.")
    with col2:
        auth_code_input = st.text_input("Paste Auth Code here", type="password")
        if st.button("🔑 Submit Auth Code", width="stretch") and auth_code_input:
            from auth_handler import _handler
            success, msg = _handler.handle_auth_code(auth_code_input)
            if success: st.success("✅ Token saved! Refreshing..."); st.rerun()
            else: st.error(f"❌ Error: {msg}")

if not data_loader.get_fyers_client():
    if "Fyers" in selected_data_source or "Auto" in selected_data_source:
        show_fyers_auth_ui()
        st.stop()
else:
    st.sidebar.success("✅ Fyers API Connected")
    with st.sidebar.expander("🔑 Refresh Fyers Token"):
        st.info("Token expires daily at 11:59 PM")
        if st.button("🔄 Force Token Refresh"):
            from auth_handler import _handler as auth_manager
            auth_manager.fyers = None
            auth_manager._last_validated = 0
            st.rerun()

try:
    if "50" in selected_universe: symbols = data_loader.get_nifty50_symbols()
    elif "100" in selected_universe: symbols = data_loader.get_nifty200_symbols()[:100]
    elif "200" in selected_universe: symbols = data_loader.get_nifty200_symbols()
    elif "500" in selected_universe: symbols = data_loader.get_nifty500_symbols()
    else: symbols = data_loader.get_index_constituents(selected_universe)
    st.info(f"📊 Universe: *{selected_universe}* — **{len(symbols)} stocks** | ⏱ Interval: *{selected_timeframe}*")
except Exception as e:
    st.error(f"Error fetching universe: {e}"); symbols = []

if st.button("🚀 Start Market Scan", width="stretch"):
    if not symbols: st.error("No valid symbols found.")
    else:
        ds_map = {"🔄 Auto (Fyers → Yahoo API → yfinance)": "auto", "Fyers API Only": "fyers", "Yahoo Finance Direct API": "yahoo", "yfinance Library": "yfinance"}
        data_loader.set_data_source(ds_map.get(selected_data_source, "auto"))
        progress_bar = st.progress(0, text="Initializing scan...")
        status_text = st.empty()
        def update_progress(completed, total):
            pct = completed / total
            progress_bar.progress(pct, text=f"Scanning {completed}/{total} stocks...")
        with st.spinner(f"Scanning {len(symbols)} stocks on {selected_timeframe} timeframe..."):
            t0 = datetime.now()
            results_df = scanner.scan_market(symbols, interval=selected_timeframe, progress_callback=update_progress)
            elapsed = (datetime.now() - t0).total_seconds()
            progress_bar.empty(); status_text.empty()
            if not results_df.empty:
                st.session_state.results_df = results_df.sort_values(by='Signal Time', ascending=False)
                fresh_count = len(results_df[results_df['signal_type'].str.contains('FRESH', na=False)])
                dual_count = len(results_df[results_df['signal_type'].str.contains('DUAL', na=False)])
                st.toast(f"✅ Scan completed in {elapsed:.1f}s | FRESH:{fresh_count} DUAL:{dual_count}", icon="⚡")
            else:
                st.session_state.results_df = "EMPTY"
                st.toast(f"✅ Scan completed in {elapsed:.1f}s | No signals found", icon="ℹ️")
        st.session_state.scan_logs = list(log_lines)
        log_lines.clear()

if "results_df" in st.session_state and isinstance(st.session_state.results_df, pd.DataFrame) and not st.session_state.results_df.empty:
    results_df = st.session_state.results_df.copy()
    st.markdown("---")
    st.markdown("### 📈 Scan Results")
    if 'signal_type' in results_df.columns:
        if signal_filter == "🚀 FRESH (Early Detection)": results_df = results_df[results_df['signal_type'].str.contains('FRESH', na=False)]
        elif signal_filter == "🔥⚡ DUAL (Intraday+Swing)": results_df = results_df[results_df['signal_type'].str.contains('DUAL', na=False)]
        elif signal_filter == "🔥 IGNITION": results_df = results_df[results_df['signal_type'].str.contains('IGNITION', na=False)]
        elif signal_filter == "⚡ INTRADAY": results_df = results_df[results_df['signal_type'].str.contains('INTRADAY', na=False)]
        elif signal_filter == "🌊 SWING": results_df = results_df[results_df['signal_type'].str.contains('SWING', na=False)]
        elif signal_filter == "Pine BUY Only": results_df = results_df[results_df['Pine Signal'] == 'BUY']
        elif signal_filter == "Exclude Decay": results_df = results_df[~results_df['signal_type'].str.contains('FADING|DISTRIBUTION', na=False, regex=True)]
    if results_df.empty: st.warning("No signals match your filter.")
    else:
        st.success(f"🎯 Found **{len(results_df)}** signals!")
        def style_signal(val):
            if 'FRESH' in str(val): return "background-color: #0d47a1; color: white; font-weight: bold;"
            elif 'DUAL' in str(val): return "background-color: #e65100; color: white; font-weight: bold;"
            elif 'IGNITION' in str(val): return "background-color: #b71c1c; color: white; font-weight: bold;"
            elif 'INTRADAY' in str(val): return "background-color: #1b5e20; color: white; font-weight: bold;"
            elif 'SWING' in str(val): return "background-color: #4a148c; color: white; font-weight: bold;"
            elif 'FADING' in str(val) or 'DISTRIBUTION' in str(val): return "background-color: #424242; color: #ff8a80;"
            return ""
        display_cols = ['Stock Name', 'LTP', 'signal_type', 'ignition_score', 'intraday_score', 'swing_score', 'RSI', 'RVOL', 'Dist_EMA21', 'ADX', 'BBW', 'Pine Signal', 'Signal Time']
        display_cols = [c for c in display_cols if c in results_df.columns]
        other_cols = [c for c in results_df.columns if c not in display_cols]
        ordered_cols = display_cols + other_cols
        styled_df = results_df[ordered_cols].style.map(style_signal, subset=["signal_type"])
        st.dataframe(styled_df, hide_index=True, width="stretch")
        col1, col2 = st.columns(2)
        with col1:
            csv = results_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Results (CSV)", csv, "results.csv", "text/csv", width="stretch")
        with col2:
            if st.button("📤 Send to Telegram", width="stretch"):
                if send_to_telegram(results_df, selected_universe, selected_timeframe): st.success("✅ Sent!")
                else: st.error("❌ Failed")

# Historical Data Viewer
st.markdown("---")
st.markdown("### 📜 Historical Data Viewer")
if "results_df" in st.session_state and isinstance(st.session_state.results_df, pd.DataFrame) and not st.session_state.results_df.empty:
    with st.expander("View Raw OHLCV Data with Indicators", expanded=False):
        col_h1, col_h2, col_h3 = st.columns([2, 1, 1])
        with col_h1: selected_stock = st.selectbox("Select Stock", sorted(st.session_state.results_df['Stock Name'].unique().tolist()))
        with col_h2: show_indicators = st.checkbox("Show Indicators", value=True)
        with col_h3: filter_mode = st.radio("Filter by", ["Date Range", "Last N Candles"], horizontal=True)
        if selected_stock:
            df_hist = data_loader.fetch_data(selected_stock, interval=selected_timeframe)
            df_hist = df_hist[~df_hist.index.duplicated(keep='last')]
            if not df_hist.empty:
                data_min_date = df_hist.index[0].date()
                data_max_date = df_hist.index[-1].date()
                if filter_mode == "Date Range":
                    cd1, cd2 = st.columns(2)
                    with cd1: start_date = st.date_input("Start Date", value=data_min_date, min_value=data_min_date, max_value=data_max_date)
                    with cd2: end_date = st.date_input("End Date", value=data_max_date, min_value=data_min_date, max_value=data_max_date)
                    df_view = df_hist[(df_hist.index.date >= start_date) & (df_hist.index.date <= end_date)].copy()
                else:
                    num_candles = st.number_input("Candles to show", min_value=10, max_value=500, value=50, step=10)
                    df_view = df_hist.tail(int(num_candles)).copy()
                if df_view.empty: st.warning("No data in selected range.")
                else:
                    if show_indicators:
                        try:
                            df_view['EMA5'] = indicators.calculate_ema(df_hist, 5).reindex(df_view.index)
                            df_view['EMA9'] = indicators.calculate_ema(df_hist, 9).reindex(df_view.index)
                            df_view['EMA21'] = indicators.calculate_ema(df_hist, 21).reindex(df_view.index)
                            df_view['EMA50'] = indicators.calculate_ema(df_hist, 50).reindex(df_view.index)
                            df_view['RSI'] = indicators.calculate_rsi(df_hist).reindex(df_view.index)
                            stoch_k = indicators.calculate_stoch_rsi(df_hist)
                            if stoch_k is not None: df_view['StochRSI_K'] = stoch_k.reindex(df_view.index)
                            macd_line, signal_line, macd_hist = indicators.calculate_macd(df_hist)
                            df_view['MACD'] = macd_line.reindex(df_view.index)
                            df_view['MACD_Signal'] = signal_line.reindex(df_view.index)
                            df_view['MACD_Hist'] = macd_hist.reindex(df_view.index)
                            df_view['ADX'] = indicators.calculate_adx(df_hist).reindex(df_view.index)
                            atr_val = indicators.calculate_atr(df_hist)
                            if atr_val is not None: df_view['ATR'] = atr_val.reindex(df_view.index)
                            df_view['RVOL'] = indicators.calculate_rvol(df_hist).reindex(df_view.index)
                            vwap_val = indicators.calculate_vwap(df_hist)
                            if vwap_val is not None: df_view['VWAP'] = vwap_val.reindex(df_view.index)
                        except Exception as e: st.warning(f"Indicator error: {e}")
                    df_display = df_view.copy()
                    df_display.index = df_display.index.strftime('%Y-%m-%d %H:%M')
                    df_display.index.name = 'Datetime'
                    st.dataframe(df_display.style.format(precision=2, na_rep='—'), height=min(600, len(df_display) * 35 + 40), width="stretch")
                    if filter_mode == "Date Range": st.markdown(f"**{selected_stock}** | {len(df_view)} candles | {start_date} to {end_date} | {selected_timeframe}")
                    else: st.markdown(f"**{selected_stock}** | {len(df_view)} candles | last {num_candles} bars | {selected_timeframe}")
                    csv_hist = df_display.to_csv().encode('utf-8')
                    st.download_button("📥 Download Filtered (CSV)", csv_hist, f"{selected_stock}_history.csv", "text/csv", width="stretch")
            else: st.warning(f"No data for {selected_stock}")
else: st.caption("Run a scan first to view historical data.")

# Scoring explanation
st.markdown("---")
st.markdown("### 🧠 3-Score System Explained")
c1, c2, c3 = st.columns(3)
with c1: st.info("#### 🔥 Ignition (0-100)\nMACD flip: +30\nRSI 45+: +25\nEMA9 reclaim: +20\nVol swell: +15\nSupertrend flip: +15\nEMA 13x34: +20")
with c2: st.success("#### ⚡ Intraday (0-100)\nVWAP pos: +20\nORB30: +20\nRVOL: +15\nEMA stack: +15\nADX: +10\nRSI sweet: +10")
with c3: st.warning("#### 🌊 Swing (0-100)\nBBW squeeze: +20\nRel Strength: +20\nEMA structure: +15\nMACD build: +15\nEMA 34x89: +12\nADX: +10")

st.markdown("---")
st.markdown("### 🏷️ Signal Types")
ct = st.columns(5)
ct[0].markdown("**🚀 FRESH**\nIgnition ≥ 35, RSI < 70, Dist < 6%")
ct[1].markdown("**🔥⚡ DUAL**\nIntraday ≥ 55, Swing ≥ 55")
ct[2].markdown("**🔥 IGNITION**\nIgnition ≥ 40")
ct[3].markdown("**⚡ INTRADAY**\nIntraday ≥ 45")
ct[4].markdown("**🌊 SWING**\nSwing ≥ 40")

# Scan logs
st.markdown("---")
st.markdown("### 📋 Scan Logs")
if "scan_logs" in st.session_state and st.session_state.scan_logs:
    with st.expander("Show scan logs", expanded=False):
        for line in st.session_state.scan_logs[-100:]:
            if "[ERROR]" in line: st.error(line)
            elif "[WARNING]" in line: st.warning(line)
            elif "[INFO]" in line: st.info(line)
            else: st.text(line)
else: st.caption("Logs appear after a scan.")
```

---

## STEP 10: automation_bot.py

```python
import os, logging, sys, time
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

import config, scanner, data_loader, reporter

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)
SCAN_UNIVERSE = config.SCAN_UNIVERSE
SCAN_INTERVAL = config.SCAN_INTERVAL

IST = pytz.timezone('Asia/Kolkata')
SCHEDULED_HOURS = [9, 10, 11, 12, 13, 14, 15]
SCHEDULED_MINUTE = 16

def get_universe_symbols():
    if SCAN_UNIVERSE == "Nifty 50": return data_loader.get_nifty50_symbols()
    elif SCAN_UNIVERSE == "Nifty 200": return data_loader.get_nifty200_symbols()
    elif SCAN_UNIVERSE == "Nifty 500": return data_loader.get_nifty500_symbols()
    else: return data_loader.get_index_constituents(SCAN_UNIVERSE)

def run_scan():
    import requests
    now_ist = datetime.now(IST)
    logger.info(f"Scanning {SCAN_UNIVERSE} ({SCAN_INTERVAL})...")
    symbols = get_universe_symbols()
    logger.info(f"Got {len(symbols)} symbols")

    nifty_df = data_loader.fetch_data("^NSEI", interval=SCAN_INTERVAL)
    results_df = scanner.scan_market(symbols, interval=SCAN_INTERVAL)

    if not results_df.empty:
        report_parts = reporter.generate_report(results_df, SCAN_UNIVERSE, SCAN_INTERVAL)
        csv_data = results_df.to_csv(index=False).encode('utf-8')
        doc_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        files = {'document': ('scan.csv', csv_data)}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': report_parts[0] if report_parts else 'Scan complete', 'parse_mode': 'Markdown'}
        try:
            requests.post(doc_url, files=files, data=data, timeout=20)
            msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            for part in report_parts[1:]:
                requests.post(msg_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": part, "parse_mode": "Markdown"}, timeout=20)
            logger.info("✅ Results sent to Telegram")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    elif config.SEND_IF_EMPTY:
        msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try: requests.post(msg_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": "📊 NSE Scanner: No signals found."}, timeout=20)
        except: pass

def main():
    logger.info("NSE Scanner 2.0 - Automation Bot")
    ds = os.environ.get("DATA_SOURCE", "auto")
    data_loader.set_data_source(ds)
    logger.info(f"📡 Data source: {ds}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials missing"); sys.exit(1)
    if os.environ.get("TEST_RUN") == "1" or os.environ.get("GITHUB_ACTIONS") == "true":
        run_scan()
    if os.environ.get("ONCE") == "1" or os.environ.get("GITHUB_ACTIONS") == "true":
        return
    last_run_id = ""
    while True:
        now_ist = datetime.now(IST)
        run_id = f"{now_ist.strftime('%Y-%m-%d')}-{now_ist.hour}"
        if now_ist.weekday() < 5 and now_ist.hour in SCHEDULED_HOURS and now_ist.minute >= SCHEDULED_MINUTE:
            if run_id != last_run_id:
                run_scan()
                last_run_id = run_id
        if now_ist.hour >= 15 and now_ist.minute > 30: last_run_id = ""
        if now_ist.hour == 0 and now_ist.minute == 0: last_run_id = ""
        time.sleep(30)

if __name__ == "__main__":
    main()
```

---

## STEP 11: .gitignore

```
.env
__pycache__/
*.pyc
*.pickle
cache/
.streamlit/secrets.toml
.idea/
.vscode/
venv/
.venv/
*.log
.DS_Store
```

---

## STEP 12: .streamlit/config.toml

```toml
[server]
headless = true
port = 8501
enableCORS = false
enableXsrfProtection = false

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#FF4B4B"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#262730"
textColor = "#FAFAFA"
```

---

## STEP 13: .streamlit/secrets.toml.example

```toml
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token_here"
TELEGRAM_CHAT_ID = "your_telegram_chat_id_here"
FYERS_CLIENT_ID = "TXFO4W8QZ3-100"
FYERS_SECRET_KEY = "your_fyers_secret_key_here"
FYERS_REDIRECT_URI = "https://your-app-name.streamlit.app/"
FYERS_ID = "FAI18742"
FYERS_PIN = "your_fyers_pin_here"
FYERS_TOTP_SECRET = "your_fyers_totp_secret_here"
FYERS_ACCESS_TOKEN = ""
```

---

## STEP 14: run_localhost.sh

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -f "venv/bin/activate" ]; then source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then source .venv/bin/activate; fi

pip install -q -r requirements.txt

select_data_source() {
    echo ""; echo "📡 Select Data Source:"
    echo "1) 🔄 Auto (Fyers → Yahoo API → yfinance)"
    echo "2) Fyers API Only"
    echo "3) Yahoo Finance Direct API"
    echo "4) yfinance Library"
    read -p "Enter Choice [1-4] (default=1): " DSChoice
    case $DSChoice in
        2) export DATA_SOURCE="fyers" ;;
        3) export DATA_SOURCE="yahoo" ;;
        4) export DATA_SOURCE="yfinance" ;;
        *) export DATA_SOURCE="auto" ;;
    esac
    echo "📡 Data source: $DATA_SOURCE"
}

while true; do
    echo ""; echo "1) 📊 Launch Streamlit Dashboard"
    echo "2) 🤖 Run Automation Bot"
    echo "3) 🚀 Quick Test Scan"
    echo "4) 🚪 Exit"
    read -p "Enter Choice [1-4]: " Choice
    case $Choice in
        1) select_data_source; streamlit run app.py ;;
        2) select_data_source; python3 automation_bot.py ;;
        3) select_data_source; export TEST_RUN=1 ONCE=1; python3 automation_bot.py; read -p "Press Enter..." dummy ;;
        4) exit 0 ;;
        *) echo "❌ Invalid choice" ;;
    esac
done
```

---

## STEP 15: git_push.sh

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
COMMIT_MSG="${1:-Update NSE Scanner}"
if [ ! -d ".git" ]; then
    git init; read -p "GitHub repo URL: " REPO_URL; git remote add origin "$REPO_URL"
fi
git add -A
git commit -m "$COMMIT_MSG

🤖 Generated with OpenClaude"
BRANCH=$(git branch --show-current 2>/dev/null || echo "main")
git push -u origin "$BRANCH"
echo "✅ Pushed to $BRANCH"
```

---

## VERIFICATION COMMANDS

```bash
# Install
cd nse2_automation
pip install -r requirements.txt

# Test imports
python3 -c "import scanner, data_loader, indicators, reporter, config; print('OK')"

# Test with Yahoo (no Fyers needed)
python3 -c "
import data_loader, scanner
data_loader.set_data_source('yahoo')
df = data_loader.fetch_data('NSE:RELIANCE-EQ', interval='1h')
print(f'RELIANCE: {len(df)} bars')
results = scanner.check_conditions(df, 'NSE:RELIANCE-EQ')
print(f'Signals: {len(results)}')
for r in results:
    print(f'  {r[\"signal_type\"]} | IGN:{r[\"ignition_score\"]}')
"

# Run
bash run_localhost.sh
```

---

## CRITICAL RULES FOR AI

1. **SMI**: Use Blau's formula (high/low/close, scale -100 to +100). NEVER use library's Ergodic/TSI version.
2. **VWAP**: Manual implementation only. Library version causes timezone warnings.
3. **BB Width**: Compute from BBL/BBM/BBU manually. Library BBB is 100x scale.
4. **MACD return order**: `(line, signal, histogram)`. Library columns are `[line, histogram, signal]`. Map correctly.
5. **Indicator guards**: Check `len(df) < length` before calling library. Return safe defaults.
6. **Duplicate timestamps**: Always deduplicate after Fyers fetch. `df = df[~df.index.duplicated(keep='last')]`
7. **Data source routing**: `fetch_data_batch()` routes to `fetch_data_batch_fast()` for yahoo/yfinance (20 workers, no sleep).
8. **Rate limiter**: Shared `threading.Lock` with `_global_rate_limit_backoff()` for Fyers.
9. **Scanner lookback**: Last 5 bars, not just today's candles.
10. **Decay bypass**: Skip penalty if MACD histogram just crossed positive.
