import pandas as pd
import numpy as np
import indicators
import data_loader
import pytz
import logging

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


def check_conditions(df, symbol, daily_df=None, close_method="Intraday Candle Close", bhavcopy_lookup=None):
    """
    CPR-only scanner — computes ATR-Normalized CPR levels + S/R.
    Returns all candles from the last trading day.
    daily_df: daily OHLC data for accurate CPR calculation (avoids hourly aggregation mismatch)
    """
    if df.empty or len(df) < 20:
        return []

    # Remove duplicate timestamps
    df = df[~df.index.duplicated(keep='last')]

    close = df['close']
    volume = df['volume']

    # CPR (Central Pivot Range) with ATR normalization — use daily OHLC for accuracy
    cpr_df = indicators.calculate_cpr(
        df,
        daily_df=daily_df,
        symbol=symbol,
        close_method=close_method,
        bhavcopy_lookup=bhavcopy_lookup
    )

    # Get all bars from the last date
    last_date = df.index[-1].date()
    last_day_mask = df.index.date == last_date
    last_day_indices = df.index[last_day_mask].tolist()

    results = []

    for idx in last_day_indices:
        try:
            pos = df.index.get_loc(idx)
            if isinstance(pos, slice):
                pos = pos.start
            elif isinstance(pos, np.ndarray):
                pos = int(np.where(pos)[0][0])

            c = close.iloc[pos]
            v = volume.iloc[pos]

            cpr_type = cpr_df['CPR_Type'].iloc[pos] if cpr_df['CPR_Type'].iloc[pos] else ''
            cpr_tc = cpr_df['CPR_TC'].iloc[pos] if not pd.isna(cpr_df['CPR_TC'].iloc[pos]) else None
            cpr_bc = cpr_df['CPR_BC'].iloc[pos] if not pd.isna(cpr_df['CPR_BC'].iloc[pos]) else None

            # LTP position relative to CPR
            if cpr_tc and cpr_bc:
                if c > cpr_tc:
                    cpr_position = "ABOVE TC (Bullish)"
                elif c < cpr_bc:
                    cpr_position = "BELOW BC (Bearish)"
                else:
                    cpr_position = "INSIDE CPR (Neutral)"
            else:
                cpr_position = ""

            result = {
                'Stock Name': symbol,
                'Open': round(df['open'].iloc[pos], 2),
                'High': round(df['high'].iloc[pos], 2),
                'Low': round(df['low'].iloc[pos], 2),
                'Close': round(c, 2),
                'CPR_Position': cpr_position,
                'Signal Time': idx.strftime('%d-%m-%Y %H:%M'),
                'Volume': int(v),
                'Prev_Open': cpr_df['Prev_Open'].iloc[pos] if not pd.isna(cpr_df['Prev_Open'].iloc[pos]) else '',
                'Prev_High': cpr_df['Prev_High'].iloc[pos] if not pd.isna(cpr_df['Prev_High'].iloc[pos]) else '',
                'Prev_Low': cpr_df['Prev_Low'].iloc[pos] if not pd.isna(cpr_df['Prev_Low'].iloc[pos]) else '',
                'Prev_Close': cpr_df['Prev_Close'].iloc[pos] if not pd.isna(cpr_df['Prev_Close'].iloc[pos]) else '',
                'CPR_PP': cpr_df['CPR_PP'].iloc[pos] if not pd.isna(cpr_df['CPR_PP'].iloc[pos]) else '',
                'CPR_BC': cpr_bc if cpr_bc else '',
                'CPR_TC': cpr_tc if cpr_tc else '',
                'CPR_Width': cpr_df['CPR_Width'].iloc[pos] if not pd.isna(cpr_df['CPR_Width'].iloc[pos]) else '',
                'CPR_ATR': cpr_df['CPR_ATR'].iloc[pos] if not pd.isna(cpr_df['CPR_ATR'].iloc[pos]) else '',
                'CPR_ATR_Ratio': cpr_df['CPR_ATR_Ratio'].iloc[pos] if not pd.isna(cpr_df['CPR_ATR_Ratio'].iloc[pos]) else '',
                'CPR_Type': cpr_type,
                'CPR_R1': cpr_df['CPR_R1'].iloc[pos] if not pd.isna(cpr_df['CPR_R1'].iloc[pos]) else '',
                'CPR_R2': cpr_df['CPR_R2'].iloc[pos] if not pd.isna(cpr_df['CPR_R2'].iloc[pos]) else '',
                'CPR_R3': cpr_df['CPR_R3'].iloc[pos] if not pd.isna(cpr_df['CPR_R3'].iloc[pos]) else '',
                'CPR_S1': cpr_df['CPR_S1'].iloc[pos] if not pd.isna(cpr_df['CPR_S1'].iloc[pos]) else '',
                'CPR_S2': cpr_df['CPR_S2'].iloc[pos] if not pd.isna(cpr_df['CPR_S2'].iloc[pos]) else '',
                'CPR_S3': cpr_df['CPR_S3'].iloc[pos] if not pd.isna(cpr_df['CPR_S3'].iloc[pos]) else '',
                'Prev_Volume': cpr_df['Prev_Volume'].iloc[pos] if not pd.isna(cpr_df['Prev_Volume'].iloc[pos]) else '',
            }

            results.append(result)

        except Exception as e:
            logger.warning(f"Error at {idx} for {symbol}: {e}")
            continue

    return results


def scan_market(symbols, interval='1d', progress_callback=None, close_method="Intraday Candle Close"):
    """
    CPR Scanner — fetches data and computes ATR-Normalized CPR for all stocks.
    Fetches daily OHLC separately for accurate CPR levels.
    """
    import time as _time
    t0 = _time.time()
    all_results = []
    total = len(symbols)

    # === PHASE 1: BATCH DATA PREFETCH ===
    logger.info(f"Phase 1: Pre-fetching {total} symbols ({interval})...")
    t1 = _time.time()
    data_cache = data_loader.fetch_data_batch(symbols, interval=interval, max_workers=4)
    t2 = _time.time()
    logger.info(f"Phase 1 complete: {len(data_cache)}/{total} symbols in {t2-t1:.1f}s")

    # Fetch daily OHLC for accurate CPR (only if using intraday timeframe)
    daily_cache = {}
    if interval in ['1h', '15m', '5m', '1m', '30m']:
        logger.info(f"Phase 1b: Fetching daily OHLC for accurate CPR...")
        t1b = _time.time()
        daily_cache = data_loader.fetch_data_batch(symbols, interval='1d', max_workers=4)
        logger.info(f"Phase 1b complete: {len(daily_cache)}/{total} daily in {_time.time()-t1b:.1f}s")

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
            if len(unique_dates) >= 2:
                prev_trading_date = unique_dates[-2]
                logger.info(f"Detected previous trading date for Bhavcopy lookup: {prev_trading_date}")
                bhavcopy_lookup = data_loader.load_bhavcopy_lookup(prev_trading_date)
                if not bhavcopy_lookup:
                    logger.warning(f"Bhavcopy lookup not resolved for date {prev_trading_date}. Falling back to default.")
            else:
                logger.warning(f"Insufficient dates in dataset to determine previous trading date: {unique_dates}")
        else:
            logger.warning("No data found in cache, cannot resolve previous trading date.")

    completed_count = 0

    for sym in symbols:
        try:
            df = data_cache.get(sym)
            if df is None or df.empty:
                completed_count += 1
                continue

            daily_df = daily_cache.get(sym) if daily_cache else None
            results = check_conditions(
                df,
                sym,
                daily_df=daily_df,
                close_method=close_method,
                bhavcopy_lookup=bhavcopy_lookup
            )
            if results:
                all_results.extend(results)
            completed_count += 1

            if progress_callback:
                progress_callback(min(completed_count, total), total)

        except Exception as e:
            logger.warning(f"Compute error for {sym}: {type(e).__name__}: {e}")
            completed_count += 1
            continue

    results_df = pd.DataFrame(all_results)

    t_end = _time.time()
    logger.info(f"Scan complete: {len(results_df)} stocks from {len(data_cache)} fetched in {t_end-t0:.1f}s")

    if not results_df.empty:
        return results_df.sort_values(by='CPR_ATR_Ratio', ascending=True)
    return pd.DataFrame()
