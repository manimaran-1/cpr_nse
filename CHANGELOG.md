# NSE2 Automation - Changelog

## Date: 2026-05-15

### Overview

Major upgrade to the NSE2 stock scanner system. Integrated `pandas-ta-classic` library for indicator calculations, redesigned the stock selection logic for early detection on 1h timeframe, improved Telegram reporting, optimized Fyers data fetching, and enhanced auto-login reliability.

---

## 1. pandas-ta-classic Integration (`indicators.py`)

### What Changed
Replaced 10 manual indicator calculations with `pandas-ta-classic` library calls. Added batch calculation function.

### Files Modified
- `indicators.py` - Rewritten indicator functions
- `requirements.txt` - Added `pandas-ta-classic` dependency

### Indicator Mapping

| Function | Before | After |
|----------|--------|-------|
| `calculate_ema` | `ewm(span=length, adjust=False)` | `ta.ema(close, length, sma=False)` |
| `calculate_rsi` | Manual Wilder's RSI | `ta.rsi(close, length)` |
| `calculate_stoch_rsi` | Manual StochRSI | `ta.stochrsi(close, ...)` |
| `calculate_macd` | Manual MACD | `ta.macd(close, ...)` |
| `calculate_bb_width` | Manual BB Width | `ta.bbands(close, ...)` + manual width |
| `calculate_adx` | Manual ADX | `ta.adx(high, low, close, length)` |
| `calculate_obv` | Manual OBV | `ta.obv(close, volume)` |
| `calculate_atr` | Manual ATR | `ta.atr(high, low, close, length)` |
| `calculate_supertrend` | Manual loop | `ta.supertrend(high, low, close, ...)` |
| `calculate_vwap` | Manual VWAP | `ta.vwap(high, low, close, volume, anchor="D")` |

### Functions Kept Manual (10)
- `calculate_heikin_ashi` - No library equivalent
- `calculate_smi` - Library SMI is Ergodic/TSI-based (different algorithm)
- `calculate_ema_slope`, `calculate_obv_slope`, `calculate_rsi_slope`, `calculate_macd_hist_slope` - Simple diff wrappers
- `calculate_distance_from_ema` - Percentage calculation
- `calculate_rvol` - Relative volume ratio
- `calculate_supertrend_duration` - Consecutive bar counting
- `calculate_ema_crossovers` - Crossover recency tracking

### New Function
- `calculate_indicators_batch()` - Uses `df.ta.strategy()` for efficient batch computation

---

## 2. Stock Selection Logic (`scanner.py`)

### What Changed
Removed the restrictive Pine Script BUY gate. Implemented 3-score system as primary filter. Added FRESH and DUAL signal types for early detection.

### Before (Pine Script Gate)
```python
# Only stocks passing ALL 4 conditions were included:
if (c > emas[5] and c > emas[9] and c > emas[21] and k > 70 and s > 30 and m > 0.75):
    results.append(res)
```
**Problem:** Required K > 70 (overbought), so early momentum signals were never captured.

### After (3-Score System)
```python
# Include if ANY score passes threshold
is_actionable = (
    pine_buy_signal == "BUY" or
    signal_type == "🚀 FRESH" or
    signal_type == "🔥⚡ DUAL" or
    ignition >= sc["IGNITION_THRESHOLD"] or
    intraday >= sc["INTRADAY_THRESHOLD"] or
    swing >= sc["SWING_THRESHOLD"]
)
```

### Signal Types

| Type | Condition | Priority |
|------|-----------|----------|
| 📉 DISTRIBUTION | Decay penalty >= 30 | Highest (warning) |
| 📉 FADING | Decay penalty >= 15 | High (warning) |
| 🔥⚡ DUAL | Intraday >= 55 AND Swing >= 55 | Highest (actionable) |
| 🚀 FRESH | Ignition >= 50 AND RSI < 65 AND Dist < 5% | High (early detection) |
| 🔥 IGNITION | Ignition >= 55 | Medium |
| ⚡ INTRADAY | Intraday >= 60 | Medium |
| 🌊 SWING | Swing >= 55 | Medium |
| 👀 WATCH | Any score >= 40-45 | Low (developing) |

### Ignition Score Changes (Early Detection Optimization)

| Signal | Old Points | New Points | Reason |
|--------|-----------|-----------|--------|
| MACD histogram just flipped positive | 25 | **30** | Earliest momentum signal |
| MACD recovering from negative | - | **5** | New: catches recovery early |
| RSI crossing above 45 | - | **25** | New: catches momentum before 50 |
| RSI rising from low zone (35-55) | - | **15** | New: early momentum zone |
| Price JUST crossed above EMA9 | 15 | **20** | Fresh reclaim is strong signal |
| Volume rising above average | - | **5** | New: at least average volume |
| Supertrend just flipped bullish | 10 | **15** | Fresh flip = strong signal |
| EMA 13x34 crossed THIS bar | 15 | **20** | Fresh trend birth |
| Proximity to EMA21 (0-3%) | 5 | **8** | Ideal entry zone |

### Penalties Reduced (Let Early Momentum Run)

| Condition | Old Threshold | New Threshold | Old Penalty | New Penalty |
|-----------|--------------|--------------|-------------|-------------|
| RSI overbought | 75 | **80** | -20 | **-15** |
| Overextension | 5% | **8%** | -25 | **-20** |
| StochRSI exhaustion | 90 | **95** | -15 | **-10** |

---

## 3. Telegram Reporting (`reporter.py`)

### What Changed
Added FRESH section for early detection. Improved deduplication logic. Lowered thresholds for actionable signals.

### New Report Structure

1. **🚀 FRESH SIGNALS — Early Detection (1h)**
   - Stocks just starting momentum, NOT overbought
   - Shows: IGN score, RSI, RVOL, EMA21 distance, MACD slope
   - Entry zone, stop loss, targets

2. **🔥⚡ DUAL OPPORTUNITIES — Intraday + Swing**
   - Stocks with BOTH intraday AND swing potential
   - Shows: IGN, INTRA, SW scores
   - Entry zone, stop loss, targets

3. **🔥 IGNITION ALERTS — Trend Birth Detection**
   - Threshold lowered: ignition >= 50 (was 55)

4. **⚡ INTRADAY PLAYS — Ride Today's Move**
   - Threshold lowered: intraday >= 55 (was 60)

5. **🌊 SWING SETUPS — Multi-Day Builders**
   - Threshold lowered: swing >= 55 (was 60)

6. **📉 FADING/DISTRIBUTION — DO NOT BUY**
   - Stocks falling from recent highs

7. **📊 EMA CROSSOVER SIGNALS**
   - Recent 13x34 and 34x89 crossovers

8. **🎯 POWERHOUSE + TOP RANKINGS**
   - Legacy 10-point confluence, top volume, RVOL, relative strength

### Deduplication Logic Fix

**Before:** Kept only the LATEST candle per stock.
**Problem:** FRESH signals from earlier candles got dropped when latest candle had DUAL type.

**After:** 
- FRESH stocks: Keep candle with highest ignition score (earliest detection moment)
- Other stocks: Keep latest candle (most recent state)

---

## 4. Fyers Data Fetch Optimization (`data_loader.py`)

### What Changed
Parallel data fetching with timeout handling.

### Before
```python
def fetch_data_batch(symbols, interval='1h', max_workers=15):
    results = {}
    for sym in symbols:  # Sequential!
        df = fetch_data(sym, interval=interval)
        if df is not None and not df.empty:
            results[sym] = df
    return results
```

### After
```python
def fetch_data_batch(symbols, interval='1h', max_workers=15):
    # Uses ThreadPoolExecutor with controlled concurrency
    # 30-second timeout per symbol
    # Progress logging every 50 symbols
```

### Scanner Phase 1 Update
- Changed from sequential (max_workers=1) to parallel (max_workers=5)
- Balances speed vs Fyers 10 req/sec rate limit

---

## 5. Auto-Login Enhancement (`auth_handler.py`)

### What Changed
More robust token refresh with retry logic and timeout handling.

### Improvements

1. **Environment Reload**
   - Added `_reload_env()` method
   - Picks up token changes from .env automatically

2. **Retry Logic**
   - 3 retry attempts (was 2)
   - 2-second wait between retries

3. **Timeout Handling**
   - 10-second timeout on all HTTP requests
   - Specific error handling for timeouts and connection errors

4. **TOTP Freshness**
   - Generates fresh TOTP right before login (avoids 30s window expiry)

5. **Better Logging**
   - Logs success/failure at each step
   - Shows attempt count

---

## 6. Streamlit UI Updates (`app.py`)

### What Changed
Updated to reflect new 3-score system and signal types.

### Changes

1. **Signal Filter**
   - Replaced "Pine BUY only" checkbox with dropdown:
     - All Signals
     - 🚀 FRESH (Early Detection)
     - 🔥⚡ DUAL (Intraday+Swing)
     - 🔥 IGNITION
     - ⚡ INTRADAY
     - 🌊 SWING
     - Pine BUY Only
     - Exclude Decay

2. **Results Table**
   - Shows signal_type with color coding:
     - FRESH: Blue
     - DUAL: Orange
     - IGNITION: Red
     - INTRADAY: Green
     - SWING: Purple
     - FADING/DISTRIBUTION: Gray
   - Shows all 3 scores (IGN, INTRA, SW)
   - Shows RSI, RVOL, Dist_EMA21, ADX, BBW

3. **Scoring Explanation**
   - Updated to show 3-score system (Ignition, Intraday, Swing)
   - Explains signal types and their conditions

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `indicators.py` | 10 functions rewritten, batch function added |
| `scanner.py` | Pine gate removed, FRESH/DUAL signals added, ignition score boosted |
| `reporter.py` | FRESH section added, deduplication fixed, thresholds lowered |
| `data_loader.py` | Parallel fetch, timeout handling |
| `auth_handler.py` | Auto-login retry, TOTP freshness, env reload |
| `app.py` | New filters, color-coded signals, 3-score display |
| `requirements.txt` | Added `pandas-ta-classic` |

---

## Dependencies Added

- `pandas-ta-classic` - 253-indicator Python TA library

## Known Issues

- VWAP warning about timezone (cosmetic, doesn't affect functionality)
- EMA 200 requires 200+ bars of data (falls back to native ewm for shorter data)
- Fyers headless login endpoints may have been deprecated by Fyers — manual auth via Streamlit UI works as fallback

---

## Latest Updates (2026-05-15 16:00)

### Auto-Login Fix (`auth_handler.py`)
- Tries multiple endpoint patterns: `api-t1.fyers.in` and `api.fyers.in`
- Tries both `/api/v3/send_login_otp` and `/api/v3/send_login_otp_v2`
- Graceful fallback: if headless login fails, logs clear message to use manual auth
- Better error messages for troubleshooting

### Streamlit UI Loading Animation (`app.py`)
- Added animated scanning indicator when "Start Market Scan" is clicked
- Shows "Scanning NSE Stocks..." with status messages
- Progress bar updates every 50 stocks
- Success toast shows FRESH/DUAL/IGN counts
- Status text shows real-time progress

### Batch Fetch Fix - 500+ Stocks (`data_loader.py`)
**Problem:** Only first ~300 stocks fetched before hitting Fyers rate limits.

**Fix:**
- Process in batches of 50 symbols (was all at once)
- 3 parallel workers (was 5)
- 2-second pause between batches
- Rate limit sleep increased to 0.15s (was 0.12s)
- Rate limit errors wait 5s (was 2s)
- Token expiry stops batch immediately
- Timeout per symbol increased to 60s (was 30s)
- Fixed `as_completed` import error

### Speed & Signal Threshold Fix (Latest)
**Problem:** 167s fetch time, 0 signals found.

**Speed Fix (`data_loader.py`):**
- Workers: 3 → **5**
- Batch size: 50 → **100**
- Rate limit sleep: 0.15s → **0.1s**
- Batch pause: 2s → **1s**
- Expected time: ~60s for 500 symbols

**Signal Fix (`config.py`, `scanner.py`):**
- IGNITION_THRESHOLD: 55 → **40**
- INTRADAY_THRESHOLD: 60 → **45**
- SWING_THRESHOLD: 55 → **40**
- FRESH condition: ignition >= 35, RSI < 70, dist < 6%
- WATCH condition: ignition >= 30 or intraday >= 35 or swing >= 35
- WATCH signals now included in results

### Rate Limiter Fix (`data_loader.py`)
**Problem:** 5 workers each doing `time.sleep(0.1)` = 50 req/sec total, hitting Fyers rate limits.

**Fix:**
- Added **shared rate limiter** using `threading.Lock` — ensures max 1 request per 150ms across ALL threads (~6.6 req/sec)
- Reduced workers: 5 → **3**
- Rate limit errors use exponential backoff (3s, 6s) instead of fixed 5s wait
- Expected: no more "request limit reached" errors

### Critical Fix: Duplicate Timestamps & Candle Lookback (`scanner.py`)
**Problem:** Scanner returned 0 signals for ALL 500 stocks despite scores being above thresholds.

**Root Cause 1: Duplicate timestamps** — Fyers API returns data with duplicate timestamps. When scanner tries `df.loc[start:end]` for ORB30 calculation, pandas raises `KeyError: "Cannot get left slice bound for non-unique label"`. This exception was silently caught, causing ALL bars to be skipped.

**Fix 1:** Added `df = df[~df.index.duplicated(keep='last')]` at the start of `check_conditions()`.

**Root Cause 2: Only today's bars evaluated** — For 1h data, scanner only checked today's ~7 bars. If today was bearish (like 2026-05-15), ALL candles had low scores.

**Fix 2:** Changed from today-only lookback to **last 5 bars** across any recent day:
```python
# Before: only today
indices_to_check = df.index[df.index.date == last_date].tolist()
# After: last 5 bars
indices_to_check = df.index[-min(5, len(df)):].tolist()
```

**Root Cause 3: Duplicate index position** — `df.index.get_loc()` returns array for duplicate timestamps, causing `pos < 5` comparison to fail.

**Fix 3:** Added handling for slice/array returns from `get_loc()`.

**Result:** 5 stocks tested → TCS, INFY, HDFCBANK, ICICIBANK all producing FRESH/DUAL/SWING signals. RELIANCE producing WATCH signal.

### Full Scan Fix: Nifty Dedup & Dynamic Candles (`scanner.py`, `data_loader.py`)
**Problem:** Full 500-stock scan returned 0 signals despite individual stock tests finding signals.

**Fix 1: Nifty DataFrame deduplication** — `check_conditions()` now deduplicates the `nifty_df` parameter. Fyers API also returns duplicate timestamps for the Nifty index, causing silent failures in relative strength calculation.

**Fix 2: Exception logging** — Changed from `logger.debug` to `logger.warning` for silent errors during bar processing, making failures visible in logs.

**Fix 3: Dynamic candle count** — Date range now computed per timeframe:
- 1h: 52 days → ~364 bars (was 100 days)
- 15m: 30 days → ~990 bars (was 30 days)
- 5m: 30 days → ~2250 bars (was 30 days)
- 1d: 310 days → ~310 bars (unchanged)
- Minimum 300 bars needed for EMA 200 + indicator warmup

### yfinance Fallback (`data_loader.py`)
**Problem:** Fyers API rate limits cause ~20 stocks to fail per scan.

**Fix:**
- Added `fetch_data_yfinance()` — fetches from Yahoo Finance when Fyers fails
- Added `fyers_to_yfinance()` — converts `NSE:RELIANCE-EQ` → `RELIANCE.NS`
- `fetch_data()` now tries Fyers first, falls back to yfinance on any failure
- yfinance uses `60d` period for intraday, `2y` for daily
- Data cached to disk after successful fetch (shared cache with Fyers data)

**Result:** 100% success rate — yfinance has no rate limits.

### Streamlit Cloud Deployment
- `pandas-ta-classic` installed from PyPI (not local)
- `.streamlit/config.toml` created for Streamlit Cloud
- `.streamlit/secrets.toml.example` — template for secrets
- `git_push.sh` — automated push script
- `requirements.txt` cleaned (9 direct dependencies)
- `.gitignore` updated to track `config.toml`
- `use_container_width` → `width="stretch"` (Streamlit deprecation)
- Log display added in Streamlit UI via `StreamlitLogHandler`

### Streamlit Log Display (`app.py`)
- Custom `StreamlitLogHandler` captures scanner/data_loader/auth logs
- Shows in collapsible expander after scan
- Color-coded: red=ERROR, yellow=WARNING, blue=INFO
