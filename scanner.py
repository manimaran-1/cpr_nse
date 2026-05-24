import pandas as pd
import numpy as np
import indicators
import data_loader
import pytz
import logging

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


def _fast_cpr_single(daily_df, symbol, close_method, bhavcopy_lookup, target_session, df=None, interval='1d'):
    """
    Fast CPR computation for a single date — avoids iterating all dates.
    Used when include_intraday=False. Returns a dict with CPR levels.
    """
    if daily_df is None or daily_df.empty or len(daily_df) < 2:
        return None

    # Determine which date's OHLC to use for CPR
    unique_dates = sorted(set(daily_df.index.date))
    latest_date = unique_dates[-1]

    # Resolve reference OHLC using indicators._get_ref_ohlc
    include_curr = (target_session == "Next Session")
    ref = indicators._get_ref_ohlc(latest_date, daily_df, df, interval, close_method, bhavcopy_lookup, symbol, include_current=include_curr)
    
    if ref is None:
        return None

    prev_high = ref['high']
    prev_low = ref['low']
    prev_close = ref['close']
    prev_open = ref['open']
    prev_volume = ref['volume']
    ref_date = ref['date']
    atr_val = ref['atr']

    # CPR formulas
    pp_raw = (prev_high + prev_low + prev_close) / 3
    bc_raw = (prev_high + prev_low) / 2
    tc_raw = (2 * pp_raw) - bc_raw
    if tc_raw < bc_raw:
        tc_raw, bc_raw = bc_raw, tc_raw

    pp = round(pp_raw, 2)
    bc = round(bc_raw, 2)
    tc = round(tc_raw, 2)
    width = abs(tc - bc)

    atr_ratio = round(width / atr_val, 4) if atr_val > 0 else 0.0

    # CPR Type classification
    if atr_ratio < 0.15:
        cpr_type = "EXTREME NARROW"
    elif atr_ratio < 0.30:
        cpr_type = "VERY NARROW"
    elif atr_ratio < 0.50:
        cpr_type = "NARROW"
    elif atr_ratio < 1.00:
        cpr_type = "NORMAL"
    elif atr_ratio < 1.50:
        cpr_type = "SLIGHTLY WIDE"
    elif atr_ratio < 2.00:
        cpr_type = "WIDE"
    else:
        cpr_type = "VERY WIDE"

    # Support/Resistance
    r1 = round(2 * pp - prev_low, 2)
    r2 = round(pp + (prev_high - prev_low), 2)
    r3 = round(prev_high + 2 * (pp - prev_low), 2)
    s1 = round(2 * pp - prev_high, 2)
    s2 = round(pp - (prev_high - prev_low), 2)
    s3 = round(prev_low - 2 * (prev_high - pp), 2)

    # Last close for position
    last_close = float(daily_df['close'].iloc[-1])

    if last_close > tc:
        pos = "ABOVE TC (Bullish)"
    elif last_close < bc:
        pos = "BELOW BC (Bearish)"
    else:
        pos = "INSIDE CPR (Neutral)"

    return {
        'Stock Name': symbol,
        'Prev_Day_Date': ref_date.strftime('%d-%m-%Y') if hasattr(ref_date, 'strftime') else str(ref_date),
        'Close': round(last_close, 2),
        'CPR_Position': pos,
        'Prev_Open': round(prev_open, 2),
        'Prev_High': round(prev_high, 2),
        'Prev_Low': round(prev_low, 2),
        'Prev_Close': round(prev_close, 2),
        'CPR_PP': pp,
        'CPR_BC': bc,
        'CPR_TC': tc,
        'CPR_Width': round(width, 2),
        'CPR_ATR': round(atr_val, 2),
        'CPR_ATR_Ratio': atr_ratio,
        'CPR_Type': cpr_type,
        'CPR_R1': r1,
        'CPR_R2': r2,
        'CPR_R3': r3,
        'CPR_S1': s1,
        'CPR_S2': s2,
        'CPR_S3': s3,
        'Prev_Volume': prev_volume,
    }


def check_conditions(df, symbol, daily_df=None, close_method="Intraday Candle Close",
                     bhavcopy_lookup=None, target_session="Current Session",
                     include_intraday=False, interval="1d"):
    """
    CPR-only scanner — computes ATR-Normalized CPR levels + S/R.

    include_intraday=False (default): 1 row per stock with CPR levels only.
    include_intraday=True: All candles from last trading day with OHLC/Position/Volume.
    """
    if not include_intraday:
        # FAST PATH: compute CPR for single date, no full DataFrame processing
        result = _fast_cpr_single(daily_df if daily_df is not None and not daily_df.empty else df,
                                  symbol, close_method, bhavcopy_lookup, target_session, df=df, interval=interval)
        return [result] if result else []

    # === INTRADAY MODE: Full processing ===
    if df.empty or len(df) < 20:
        return []

    df = df[~df.index.duplicated(keep='last')]

    cpr_df = indicators.calculate_cpr(
        df, daily_df=daily_df, symbol=symbol,
        close_method=close_method, bhavcopy_lookup=bhavcopy_lookup,
        target_session=target_session, interval=interval
    )

    last_date = df.index[-1].date()
    last_day_mask = df.index.date == last_date
    last_day_df = df[last_day_mask]
    last_day_cpr = cpr_df[last_day_mask]

    if last_day_df.empty:
        return []

    cpr_tc = last_day_cpr['CPR_TC'].values
    cpr_bc = last_day_cpr['CPR_BC'].values
    close_vals = last_day_df['close'].values

    cpr_position = np.where(
        (close_vals > cpr_tc) & ~np.isnan(cpr_tc),
        "ABOVE TC (Bullish)",
        np.where(
            (close_vals < cpr_bc) & ~np.isnan(cpr_bc),
            "BELOW BC (Bearish)",
            np.where(
                ~np.isnan(cpr_tc) & ~np.isnan(cpr_bc),
                "INSIDE CPR (Neutral)",
                ""
            )
        )
    )

    def _safe(series, default=''):
        return series.fillna(default).values if hasattr(series, 'fillna') else series

    def _safe_num(series):
        return series.fillna(0.0).values if hasattr(series, 'fillna') else series

    if daily_df is not None and not daily_df.empty:
        daily_dates = sorted(set(daily_df.index.date))
        if target_session == "Next Session":
            cpr_ref_date = daily_dates[-1] if daily_dates else last_date
        else:
            cpr_ref_date = daily_dates[-2] if len(daily_dates) >= 2 else daily_dates[-1]
    else:
        intra_dates = sorted(set(df.index.date))
        if target_session == "Next Session":
            cpr_ref_date = intra_dates[-1] if intra_dates else last_date
        else:
            cpr_ref_date = intra_dates[-2] if len(intra_dates) >= 2 else intra_dates[-1]

    timestamps = last_day_df.index

    result_df = pd.DataFrame({
        'Stock Name': symbol,
        'Prev_Day_Date': cpr_ref_date.strftime('%d-%m-%Y') if hasattr(cpr_ref_date, 'strftime') else str(cpr_ref_date),
        'Open': last_day_df['open'].round(2).values,
        'High': last_day_df['high'].round(2).values,
        'Low': last_day_df['low'].round(2).values,
        'Close': np.round(close_vals, 2),
        'CPR_Position': cpr_position,
        'Signal Time': [t.strftime('%d-%m-%Y %H:%M') for t in timestamps],
        'Volume': last_day_df['volume'].fillna(0).astype(int).values,
        'Prev_Open': _safe_num(last_day_cpr['Prev_Open']),
        'Prev_High': _safe_num(last_day_cpr['Prev_High']),
        'Prev_Low': _safe_num(last_day_cpr['Prev_Low']),
        'Prev_Close': _safe_num(last_day_cpr['Prev_Close']),
        'CPR_PP': _safe_num(last_day_cpr['CPR_PP']),
        'CPR_BC': _safe_num(last_day_cpr['CPR_BC']),
        'CPR_TC': _safe_num(last_day_cpr['CPR_TC']),
        'CPR_Width': _safe_num(last_day_cpr['CPR_Width']),
        'CPR_ATR': _safe_num(last_day_cpr['CPR_ATR']),
        'CPR_ATR_Ratio': _safe_num(last_day_cpr['CPR_ATR_Ratio']),
        'CPR_Type': _safe(last_day_cpr['CPR_Type']),
        'CPR_R1': _safe_num(last_day_cpr['CPR_R1']),
        'CPR_R2': _safe_num(last_day_cpr['CPR_R2']),
        'CPR_R3': _safe_num(last_day_cpr['CPR_R3']),
        'CPR_S1': _safe_num(last_day_cpr['CPR_S1']),
        'CPR_S2': _safe_num(last_day_cpr['CPR_S2']),
        'CPR_S3': _safe_num(last_day_cpr['CPR_S3']),
        'Prev_Volume': _safe_num(last_day_cpr['Prev_Volume']),
    })

    return result_df.to_dict('records')


def scan_market(symbols, interval='1d', progress_callback=None, close_method="Intraday Candle Close", target_session="Current Session", include_intraday=False):
    """
    CPR Scanner — fetches data and computes ATR-Normalized CPR for all stocks.

    include_intraday=False (default): Only fetches daily OHLC. ~50% faster.
    include_intraday=True: Fetches both intraday + daily OHLC.
    """
    import time as _time
    t0 = _time.time()
    all_results = []
    total = len(symbols)

    def _fetch_progress(done, total_fetch, label=""):
        if progress_callback:
            if label == "daily":
                pct = 0.5 * min(done / total_fetch, 1.0)
            else:
                pct = 0.5 * min(done / total_fetch, 1.0)
            progress_callback(int(pct * total), total)

    data_cache = {}
    daily_cache = {}

    should_fetch_intraday = include_intraday or (close_method == "Intraday Candle Close" and interval not in ['1d', 'D'])

    if should_fetch_intraday:
        # === PHASE 1: FETCH INTRADATA ===
        logger.info(f"Phase 1: Pre-fetching {total} symbols ({interval})...")
        t1 = _time.time()
        data_cache = data_loader.fetch_data_batch(symbols, interval=interval, max_workers=4,
                                                  progress_callback=_fetch_progress, phase_label="intraday")
        logger.info(f"Phase 1 complete: {len(data_cache)}/{total} symbols in {_time.time()-t1:.1f}s")

        # Also fetch daily OHLC for accurate CPR
        logger.info(f"Phase 1b: Fetching daily OHLC for accurate CPR...")
        t1b = _time.time()
        daily_cache = data_loader.fetch_data_batch(symbols, interval='1d', max_workers=4,
                                                   progress_callback=_fetch_progress, phase_label="daily")
        logger.info(f"Phase 1b complete: {len(daily_cache)}/{total} daily in {_time.time()-t1b:.1f}s")
    else:
        # === FAST MODE: DAILY OHLC ONLY (skip intraday fetch) ===
        logger.info(f"Phase 1: Fetching daily OHLC for {total} symbols (intraday skipped)...")
        t1 = _time.time()
        daily_cache = data_loader.fetch_data_batch(symbols, interval='1d', max_workers=4,
                                                   progress_callback=_fetch_progress, phase_label="daily")
        logger.info(f"Phase 1 complete: {len(daily_cache)}/{total} daily in {_time.time()-t1:.1f}s")

    # === PHASE 2: COMPUTE CPR ===
    logger.info("Phase 2: Computing CPR...")

    bhavcopy_lookup = None
    if close_method == "Official Exchange LTP (Bhavcopy)":
        # Resolve the previous trading date from datasets
        sample_df = None
        if daily_cache:
            for sym, df in daily_cache.items():
                if df is not None and not df.empty:
                    sample_df = df
                    break
        if sample_df is None and data_cache:
            for sym, df in data_cache.items():
                if df is not None and not df.empty:
                    sample_df = df
                    break

        if sample_df is not None:
            unique_dates = sorted(list(set(sample_df.index.date)))
            if len(unique_dates) >= 1:
                # If target is Next Session, we want today's data (latest unique date) as the baseline for tomorrow's CPR
                if target_session == "Next Session":
                    prev_trading_date = unique_dates[-1]
                else:
                    prev_trading_date = unique_dates[-2] if len(unique_dates) >= 2 else unique_dates[-1]

                logger.info(f"Detected trading date for Bhavcopy lookup ({target_session}): {prev_trading_date}")
                bhavcopy_lookup = data_loader.load_bhavcopy_lookup(prev_trading_date)
                if not bhavcopy_lookup:
                    logger.warning(f"Bhavcopy lookup not resolved for date {prev_trading_date}. Falling back to default.")
            else:
                logger.warning(f"Insufficient dates in dataset to determine baseline date: {unique_dates}")
        else:
            logger.warning("No data found in cache, cannot resolve baseline date.")

    completed_count = 0
    skipped_count = 0

    for sym in symbols:
        try:
            if should_fetch_intraday:
                # Intraday mode: use intraday data as main, daily for CPR accuracy
                df = data_cache.get(sym)
                daily_df = daily_cache.get(sym)
                if df is None or df.empty:
                    skipped_count += 1
                    completed_count += 1
                    continue
            else:
                # Fast mode: use daily data for everything
                daily_df = daily_cache.get(sym)
                df = daily_df
                if df is None or df.empty:
                    skipped_count += 1
                    completed_count += 1
                    continue

            results = check_conditions(
                df,
                sym,
                daily_df=daily_df,
                close_method=close_method,
                bhavcopy_lookup=bhavcopy_lookup,
                target_session=target_session,
                include_intraday=include_intraday,
                interval=interval
            )
            if results:
                all_results.extend(results)
            completed_count += 1

            if progress_callback and completed_count % 100 == 0:
                pct = 0.7 + 0.3 * min(completed_count / total, 1.0)
                progress_callback(int(pct * total), total)

        except Exception as e:
            logger.warning(f"Compute error for {sym}: {type(e).__name__}: {e}")
            completed_count += 1
            continue

    results_df = pd.DataFrame(all_results)

    t_end = _time.time()
    logger.info(f"Scan complete: {len(results_df)} results from {len(data_cache) - skipped_count}/{len(data_cache)} fetched in {t_end-t0:.1f}s")

    if not results_df.empty:
        return results_df.sort_values(by='CPR_ATR_Ratio', ascending=True)
    return pd.DataFrame()
