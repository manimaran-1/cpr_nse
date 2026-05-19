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

# Configure logging
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


def check_conditions(df, symbol, nifty_df=None):
    """
    Simplified scanner — computes CPR levels and Pine Signal indicators only.
    """
    strat = config.STRATEGY_CONFIG

    if df.empty or len(df) < 50:
        return []

    # Remove duplicate timestamps
    df = df[~df.index.duplicated(keep='last')]

    close = df['close']
    volume = df['volume']

    # EMAs for Pine Signal (need 5, 9, 21)
    emas = {length: indicators.calculate_ema(df, length) for length in [5, 9, 21]}

    # Core oscillators for Pine Signal
    stoch_rsi_k = indicators.calculate_stoch_rsi(df, **strat.get("STOCH_RSI", {}))
    smi = indicators.calculate_smi(df, **strat.get("SMI", {}))
    rsi = indicators.calculate_rsi(df)
    macd_line, signal_line, macd_hist = indicators.calculate_macd(df, **strat.get("MACD", {}))

    # CPR (Central Pivot Range) from previous day's data
    cpr_df = indicators.calculate_cpr(df)

    results = []

    # Intraday heuristic
    is_intraday = False
    if len(df) > 1:
        time_diff = df.index[-1] - df.index[-2]
        if time_diff < pd.Timedelta(days=1):
            is_intraday = True

    # Check last 20 bars to catch recent setups
    lookback = min(20, len(df))
    indices_to_check = df.index[-lookback:].tolist()

    for idx in indices_to_check:
        try:
            pos = df.index.get_loc(idx)
            # Handle duplicate indices
            if isinstance(pos, slice):
                pos = pos.start
            elif isinstance(pos, np.ndarray):
                pos = int(np.where(pos)[0][0])
            if pos < 5:
                continue

            c = close.iloc[pos]
            v = volume.iloc[pos]
            k = stoch_rsi_k.iloc[pos]
            s = smi.iloc[pos]
            m = macd_line.iloc[pos]
            mh = macd_hist.iloc[pos]
            r = rsi.iloc[pos]

            # Day Open for current index date
            candle_date = idx.date()
            day_data = df[df.index.date == candle_date]
            day_open_price = day_data.iloc[0]['open'] if not day_data.empty else df['open'].iloc[pos]

            # === PINE SCRIPT SIGNAL ===
            pine_ema_ok = (c > emas[5].iloc[pos]) and (c > emas[9].iloc[pos]) and (c > emas[21].iloc[pos])
            pine_stoch_ok = k > 70
            pine_smi_ok = s > 30
            pine_macd_ok = m > 0.75
            pine_buy_signal = "BUY" if (pine_ema_ok and pine_stoch_ok and pine_smi_ok and pine_macd_ok) else ""

            # Signal type based on Pine Signal and CPR
            cpr_type = cpr_df['CPR_Type'].iloc[pos] if cpr_df['CPR_Type'].iloc[pos] else ''
            if pine_buy_signal == "BUY":
                signal_type = "PINE BUY"
            else:
                signal_type = "NEUTRAL"

            res = {
                'Stock Name': symbol,
                'LTP': round(c, 2),
                'Day Open': round(day_open_price, 2) if day_open_price else round(c, 2),
                'Signal Time': idx.strftime('%d-%m-%Y %H:%M'),
                'Volume': int(v),
                'Stoch RSI K': round(k, 2),
                'RSI': round(r, 2),
                'SMI': round(s, 2),
                'MACD': round(m, 2),
                'MACD_Hist': round(mh, 2),
                'Pine Signal': pine_buy_signal,
                'signal_type': signal_type,
                # --- CPR Levels (ATR-Normalized) ---
                'CPR_PP': cpr_df['CPR_PP'].iloc[pos] if not pd.isna(cpr_df['CPR_PP'].iloc[pos]) else '',
                'CPR_BC': cpr_df['CPR_BC'].iloc[pos] if not pd.isna(cpr_df['CPR_BC'].iloc[pos]) else '',
                'CPR_TC': cpr_df['CPR_TC'].iloc[pos] if not pd.isna(cpr_df['CPR_TC'].iloc[pos]) else '',
                'CPR_Width': cpr_df['CPR_Width'].iloc[pos] if not pd.isna(cpr_df['CPR_Width'].iloc[pos]) else '',
                'CPR_ATR': cpr_df['CPR_ATR'].iloc[pos] if not pd.isna(cpr_df['CPR_ATR'].iloc[pos]) else '',
                'CPR_ATR_Ratio': cpr_df['CPR_ATR_Ratio'].iloc[pos] if not pd.isna(cpr_df['CPR_ATR_Ratio'].iloc[pos]) else '',
                'CPR_Type': cpr_type,
            }

            # Always include the result (for CPR and indicator visibility)
            results.append(res)

        except Exception as e:
            logger.warning(f"[{symbol}] Error at {idx}: {type(e).__name__}: {e}")
            continue

    return results


def scan_symbol(symbol, interval, nifty_df=None):
    """Worker function to fetch and scan a single symbol."""
    df = data_loader.fetch_data(symbol, interval=interval)
    return check_conditions(df, symbol, nifty_df=nifty_df)


def scan_market(symbols, interval='1d', progress_callback=None):
    """
    High-performance market scanner with 2-phase architecture:
    Phase 1: Sequential pre-fetch all OHLCV data (IO-bound)
    Phase 2: Compute indicators from cached data (CPU-bound, threaded)
    """
    import time as _time
    t0 = _time.time()
    all_results = []
    total = len(symbols)

    # === PHASE 1: BATCH DATA PREFETCH ===
    logger.info(f"⚡ Phase 1: Pre-fetching {total} symbols...")
    t1 = _time.time()
    data_cache = data_loader.fetch_data_batch(
        symbols, interval=interval, max_workers=4
    )
    t2 = _time.time()
    logger.info(f"✅ Phase 1 complete: {len(data_cache)}/{total} symbols in {t2-t1:.1f}s")

    # === PHASE 2: SEQUENTIAL INDICATOR COMPUTATION ===
    logger.info("⚡ Phase 2: Computing indicators...")
    completed_count = 0

    for sym in symbols:
        try:
            df = data_cache.get(sym)
            if df is None or df.empty:
                completed_count += 1
                continue

            results = check_conditions(df, sym)
            if results:
                all_results.extend(results)
            completed_count += 1

            # Update progress (clamped to 0-1)
            if progress_callback:
                progress_callback(min(completed_count, total), total)

        except Exception as e:
            import traceback
            logger.warning(f"Compute error for {sym}: {type(e).__name__}: {e}")
            logger.debug(traceback.format_exc())
            completed_count += 1
            continue

    results_df = pd.DataFrame(all_results)

    t_end = _time.time()
    logger.info(f"✅ Scan complete: {len(results_df)} signals from {len(data_cache)} stocks in {t_end-t0:.1f}s")

    if not results_df.empty:
        return results_df.sort_values(by='Signal Time', ascending=False)
    return pd.DataFrame()
