import pandas as pd
import numpy as np
import indicators
import data_loader
import pytz
import logging

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


def check_conditions(df, symbol, daily_df=None, close_method="Intraday Candle Close",
                     bhavcopy_lookup=None, target_session="Current Session",
                     include_intraday=False):
    """
    CPR-only scanner — computes ATR-Normalized CPR levels + S/R.

    include_intraday=False (default): 1 row per stock with CPR levels only.
    include_intraday=True: All candles from last trading day with OHLC/Position/Volume.
    """
    if df.empty or len(df) < 20:
        return []

    # Remove duplicate timestamps
    df = df[~df.index.duplicated(keep='last')]

    # CPR (Central Pivot Range) with ATR normalization — use daily OHLC for accuracy
    cpr_df = indicators.calculate_cpr(
        df,
        daily_df=daily_df,
        symbol=symbol,
        close_method=close_method,
        bhavcopy_lookup=bhavcopy_lookup,
        target_session=target_session
    )

    # Get all bars from the last date — vectorized
    last_date = df.index[-1].date()
    last_day_mask = df.index.date == last_date
    last_day_df = df[last_day_mask]
    last_day_cpr = cpr_df[last_day_mask]

    if last_day_df.empty:
        return []

    # Vectorized CPR position calculation
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
        """Replace NaN with default for display columns."""
        return series.fillna(default).values if hasattr(series, 'fillna') else series

    def _safe_num(series):
        """Keep numeric columns as float, replacing NaN with 0."""
        return series.fillna(0.0).values if hasattr(series, 'fillna') else series

    # Determine CPR reference date (which date's OHLC was used for CPR)
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

    # CPR-level columns (always present, 1 row per stock)
    cpr_row = {
        'Stock Name': symbol,
        'CPR_Date': cpr_ref_date.strftime('%d-%m-%Y') if hasattr(cpr_ref_date, 'strftime') else str(cpr_ref_date),
        'Prev_Open': _safe_num(last_day_cpr['Prev_Open'])[0] if len(last_day_cpr) else 0,
        'Prev_High': _safe_num(last_day_cpr['Prev_High'])[0] if len(last_day_cpr) else 0,
        'Prev_Low': _safe_num(last_day_cpr['Prev_Low'])[0] if len(last_day_cpr) else 0,
        'Prev_Close': _safe_num(last_day_cpr['Prev_Close'])[0] if len(last_day_cpr) else 0,
        'CPR_PP': _safe_num(last_day_cpr['CPR_PP'])[0] if len(last_day_cpr) else 0,
        'CPR_BC': _safe_num(last_day_cpr['CPR_BC'])[0] if len(last_day_cpr) else 0,
        'CPR_TC': _safe_num(last_day_cpr['CPR_TC'])[0] if len(last_day_cpr) else 0,
        'CPR_Width': _safe_num(last_day_cpr['CPR_Width'])[0] if len(last_day_cpr) else 0,
        'CPR_ATR': _safe_num(last_day_cpr['CPR_ATR'])[0] if len(last_day_cpr) else 0,
        'CPR_ATR_Ratio': _safe_num(last_day_cpr['CPR_ATR_Ratio'])[0] if len(last_day_cpr) else 0,
        'CPR_Type': _safe(last_day_cpr['CPR_Type'])[0] if len(last_day_cpr) else '',
        'CPR_R1': _safe_num(last_day_cpr['CPR_R1'])[0] if len(last_day_cpr) else 0,
        'CPR_R2': _safe_num(last_day_cpr['CPR_R2'])[0] if len(last_day_cpr) else 0,
        'CPR_R3': _safe_num(last_day_cpr['CPR_R3'])[0] if len(last_day_cpr) else 0,
        'CPR_S1': _safe_num(last_day_cpr['CPR_S1'])[0] if len(last_day_cpr) else 0,
        'CPR_S2': _safe_num(last_day_cpr['CPR_S2'])[0] if len(last_day_cpr) else 0,
        'CPR_S3': _safe_num(last_day_cpr['CPR_S3'])[0] if len(last_day_cpr) else 0,
        'Prev_Volume': _safe_num(last_day_cpr['Prev_Volume'])[0] if len(last_day_cpr) else 0,
    }

    if not include_intraday:
        # Default: 1 row per stock, CPR levels + last close position
        last_close = close_vals[-1]
        last_tc = cpr_tc[-1] if len(cpr_tc) else np.nan
        last_bc = cpr_bc[-1] if len(cpr_bc) else np.nan
        if not np.isnan(last_tc) and last_close > last_tc:
            pos = "ABOVE TC (Bullish)"
        elif not np.isnan(last_bc) and last_close < last_bc:
            pos = "BELOW BC (Bearish)"
        elif not np.isnan(last_tc) and not np.isnan(last_bc):
            pos = "INSIDE CPR (Neutral)"
        else:
            pos = ""
        cpr_row['Close'] = round(float(last_close), 2)
        cpr_row['CPR_Position'] = pos
        return [cpr_row]

    # include_intraday=True: All candles with OHLC/Position/Volume
    timestamps = last_day_df.index

    result_df = pd.DataFrame({
        'Stock Name': symbol,
        'CPR_Date': cpr_ref_date.strftime('%d-%m-%Y') if hasattr(cpr_ref_date, 'strftime') else str(cpr_ref_date),
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

    if include_intraday:
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
            if include_intraday:
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
                include_intraday=include_intraday
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
