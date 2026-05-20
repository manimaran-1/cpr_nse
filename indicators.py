import pandas as pd
import numpy as np
import pandas_ta_classic as ta

def calculate_heikin_ashi(df):
    """
    Calculate Heikin Ashi candles.
    Returns a new DataFrame with 'ha_open', 'ha_high', 'ha_low', 'ha_close'.
    """
    ha_df = pd.DataFrame(index=df.index)
    
    # Close: (O + H + L + C) / 4
    ha_df['close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    
    # Open: (Previous Open + Previous Close) / 2
    ha_open = np.zeros(len(df))
    ha_open[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i-1] + ha_df['close'].iloc[i-1]) / 2
    ha_df['open'] = ha_open
    
    # High: max(H, ha_open, ha_close)
    ha_df['high'] = pd.concat([df['high'], ha_df['open'], ha_df['close']], axis=1).max(axis=1)
    
    # Low: min(L, ha_open, ha_close)
    ha_df['low'] = pd.concat([df['low'], ha_df['open'], ha_df['close']], axis=1).min(axis=1)
    
    # Keep volume for compatibility
    ha_df['volume'] = df['volume']
    
    return ha_df

def calculate_ema(df, length):
    """
    Calculate Exponential Moving Average using pandas-ta-classic.
    sma=False matches the ewm(adjust=False) behavior from bar 0.
    Falls back to native ewm if data is too short for library (suppresses warning).
    """
    if len(df) < length:
        return df['close'].ewm(span=length, adjust=False).mean()
    result = ta.ema(df['close'], length=length, sma=False)
    if result is None:
        return df['close'].ewm(span=length, adjust=False).mean()
    return result.fillna(0)

def calculate_stoch_rsi(df, length=14, rsi_length=14, k=3, d=3):
    """
    Calculate Stochastic RSI using pandas-ta-classic.
    Returns the K line. mamode="sma" matches the rolling mean smoothing.
    """
    if len(df) < rsi_length + length:
        return pd.Series(0, index=df.index)
    result = ta.stochrsi(df['close'], length=length, rsi_length=rsi_length, k=k, d=d, mamode="sma")
    if result is None:
        return pd.Series(0, index=df.index)
    k_col = result.columns[0]
    return result[k_col].fillna(0)

def calculate_rsi(df, length=14):
    """
    Calculate Standard RSI using pandas-ta-classic (Wilder's smoothing).
    """
    if len(df) < length:
        return pd.Series(50, index=df.index)
    return ta.rsi(df['close'], length=length)

def calculate_bb_width(df, length=20, std_dev=2):
    """
    Calculate Bollinger Band Width for squeeze detection.
    Computed manually from BBL/BBM/BBU (library BBB is 100x scale).
    """
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.bbands(df['close'], length=length, std=std_dev)
    if result is None:
        return pd.Series(0, index=df.index)
    cols = result.columns
    lower = result[cols[0]]   # BBL
    mid = result[cols[1]]     # BBM
    upper = result[cols[2]]   # BBU
    mid_safe = mid.replace(0, np.nan)
    bb_width = (upper - lower) / mid_safe
    return bb_width.fillna(0)

def calculate_smi(df, length=10, smooth=3):
    """
    Calculate Stochastic Momentum Index matching Blau's formula as used in Pine Script (*50 scale).
    """
    hh = df['high'].rolling(window=length).max()
    ll = df['low'].rolling(window=length).min()
    
    center = (hh + ll) / 2
    diff = hh - ll
    rdiff = df['close'] - center
    
    # Blau's Double Smoothing using EMA
    num = rdiff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    den = diff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    
    # Formula: (num / (0.5 * den)) * 100  (This matches the -100 to 100 scale in Pine)
    smi = 100 * (num / (0.5 * den.replace(0, np.nan)))
    
    return smi.fillna(0)

def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD using pandas-ta-classic.
    Returns: (macd_line, signal_line, histogram)
    Library columns: [MACD, MACDh, MACDs] = [line, histogram, signal]
    """
    if len(df) < slow + signal:
        empty = pd.Series(0.0, index=df.index)
        return empty, empty, empty
    result = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)
    if result is None:
        empty = pd.Series(0.0, index=df.index)
        return empty, empty, empty
    cols = result.columns
    macd_line = result[cols[0]].fillna(0)      # MACD_12_26_9
    macd_hist = result[cols[1]].fillna(0)       # MACDh_12_26_9
    signal_line = result[cols[2]].fillna(0)     # MACDs_12_26_9
    return macd_line, signal_line, macd_hist

def calculate_vwap(df):
    """
    Calculate Intra-day VWAP with session resets.
    Uses manual implementation to avoid timezone warnings.
    """
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
    """
    Calculate ADX using pandas-ta-classic (Wilder's smoothing).
    Returns DataFrame with [ADX, DMP, DMN]; extract ADX column.
    """
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.adx(df['high'], df['low'], df['close'], length=length)
    if result is None:
        return pd.Series(0, index=df.index)
    adx_col = result.columns[0]  # ADX_{length}
    return result[adx_col].fillna(0)

def calculate_obv(df):
    """Calculate On-Balance Volume (OBV) using pandas-ta-classic."""
    return ta.obv(df['close'], df['volume'])

def calculate_atr(df, length=14):
    """Calculate Average True Range (ATR) using pandas-ta-classic."""
    if len(df) < length:
        return pd.Series(0, index=df.index)
    result = ta.atr(df['high'], df['low'], df['close'], length=length)
    if result is None:
        return pd.Series(0, index=df.index)
    return result.fillna(0)

def calculate_ema_slope(df, length=21, lookback=1):
    """Calculate the slope (difference) of an EMA."""
    ema = calculate_ema(df, length)
    return ema.diff(lookback).fillna(0)

def calculate_supertrend(df, length=10, multiplier=3):
    """
    Calculate Supertrend using pandas-ta-classic.
    Returns: (trend_line, direction) where direction is 1 (bullish) or -1 (bearish).
    Library uses numba @njit with graceful fallback.
    """
    if len(df) < length:
        empty = pd.Series(0.0, index=df.index)
        return empty, pd.Series(1, index=df.index)
    result = ta.supertrend(df['high'], df['low'], df['close'], length=length, multiplier=multiplier)
    if result is None:
        empty = pd.Series(0.0, index=df.index)
        return empty, pd.Series(1, index=df.index)
    cols = result.columns
    trend = result[cols[0]].fillna(0)       # SUPERT_{length}_{multiplier}
    direction = result[cols[1]].fillna(1)   # SUPERTd_{length}_{multiplier}
    return trend, direction

# ============================================================
# NEW INDICATORS FOR 3-SCORE SYSTEM
# ============================================================

def calculate_obv_slope(df, lookback=3):
    """
    Calculate OBV slope over `lookback` bars using simple difference.
    Positive slope = sustained accumulation (not just 1-bar noise).
    """
    obv = calculate_obv(df)
    slope = obv.diff(lookback).fillna(0)
    return slope

def calculate_rsi_slope(df, rsi_length=14, lookback=3):
    """
    Calculate RSI momentum direction over `lookback` bars.
    Positive = RSI accelerating (momentum building).
    Negative = RSI decelerating (momentum fading even if RSI is high).
    """
    rsi = calculate_rsi(df, rsi_length)
    slope = rsi.diff(lookback).fillna(0)
    return slope

def calculate_macd_hist_slope(df, fast=12, slow=26, signal=9, lookback=3):
    """
    Calculate MACD Histogram slope over `lookback` bars.
    This is THE leading momentum indicator:
    - Histogram turning from negative to positive = momentum shift
    - Histogram positive and increasing = momentum accelerating
    - Histogram positive but decreasing = momentum fading (exit warning)
    """
    _, _, hist = calculate_macd(df, fast, slow, signal)
    slope = hist.diff(lookback).fillna(0)
    return slope

def calculate_distance_from_ema(df, length):
    """
    Calculate percentage distance of close price from an EMA.
    Returns: Series of percentages.
    - Positive = price above EMA (bullish, but if too high = overextended)
    - Negative = price below EMA

    Key thresholds:
    - 0-2%: Fresh move, ideal entry zone
    - 2-5%: Moderate extension, still okay for momentum
    - 5%+: Overextended, falling knife risk
    - 8%+: Danger zone, DO NOT CHASE
    """
    ema = calculate_ema(df, length)
    ema_safe = ema.replace(0, np.nan)
    distance_pct = ((df['close'] - ema) / ema_safe) * 100
    return distance_pct.fillna(0)

def calculate_rvol(df, lookback=20):
    """
    Calculate Relative Volume (RVOL) ratio.
    Returns: Series where 1.0 = average volume, 2.0 = double average, etc.
    
    Key thresholds:
    - < 1.0: Below average (low interest)
    - 1.0-1.5: Normal
    - 1.5-2.5: Elevated (attention)
    - 2.5+: Institutional flow (high conviction)
    """
    avg_vol = df['volume'].rolling(window=lookback).mean()
    avg_vol_safe = avg_vol.replace(0, np.nan)
    rvol = df['volume'] / avg_vol_safe
    return rvol.fillna(0)

def calculate_supertrend_duration(df, length=10, multiplier=3):
    """
    Calculate how many consecutive bars the Supertrend has been bullish.
    Used by Swing Score to confirm trend persistence (not just a 1-bar flip).
    """
    _, direction = calculate_supertrend(df, length, multiplier)
    dur = pd.Series(0, index=df.index)
    count = 0
    for i in range(len(direction)):
        if direction.iloc[i] == 1:
            count += 1
        else:
            count = 0
        dur.iloc[i] = count
    return dur


def calculate_ema_crossovers(df, emas):
    """
    Detect EMA crossover events and their recency for scoring.
    
    Pairs are Fibonacci-aligned and tuned for 1h NSE candles (6.25h/day):
    
      - Fast crossover:  EMA13 × EMA34
        EMA13 = 13h ≈ 2 trading days
        EMA34 = 34h ≈ 5.5 trading days (~1 week)
        → Catches intraday/ignition trend birth without noise.
        → Crosses ~1-2 times/month per stock (vs 3-5/week for 9×21).
    
      - Medium crossover: EMA34 × EMA89
        EMA34 = 34h ≈ 5.5 trading days (~1 week)
        EMA89 = 89h ≈ 14 trading days (~3 weeks)
        → Catches swing-level trend shifts for multi-day holds.
    
    Why NOT 9×21:
      EMA9=9h(1.4d) and EMA21=21h(3.4d) are too close on hourly candles,
      causing frequent whipsaw crosses on every intraday pullback/recovery.
    
    Returns: dict with keys:
      '13x34_bull_bars', '13x34_bear_bars',
      '34x89_bull_bars', '34x89_bear_bars'
    """
    result = {}
    
    pairs = [
        (13, 34, '13x34'),
        (34, 89, '34x89'),
    ]
    
    for fast_len, slow_len, label in pairs:
        if fast_len not in emas or slow_len not in emas:
            result[f'{label}_bull_bars'] = pd.Series(np.nan, index=df.index)
            result[f'{label}_bear_bars'] = pd.Series(np.nan, index=df.index)
            continue
        
        fast_ema = emas[fast_len]
        slow_ema = emas[slow_len]
        
        # Determine position: 1 = fast above slow, -1 = fast below slow
        position = np.where(fast_ema > slow_ema, 1, -1)
        
        # Detect crossover events
        bull_bars = pd.Series(np.nan, index=df.index)
        bear_bars = pd.Series(np.nan, index=df.index)
        
        last_bull_cross = np.nan
        last_bear_cross = np.nan
        
        for i in range(1, len(position)):
            # Bullish cross: was below (or equal), now above
            if position[i] == 1 and position[i-1] == -1:
                last_bull_cross = 0
            # Bearish cross: was above (or equal), now below
            elif position[i] == -1 and position[i-1] == 1:
                last_bear_cross = 0
            
            if not np.isnan(last_bull_cross):
                bull_bars.iloc[i] = last_bull_cross
                last_bull_cross += 1
            if not np.isnan(last_bear_cross):
                bear_bars.iloc[i] = last_bear_cross
                last_bear_cross += 1
        
        result[f'{label}_bull_bars'] = bull_bars
        result[f'{label}_bear_bars'] = bear_bars

    return result


def calculate_indicators_batch(df, ema_lengths=None, stoch_rsi_params=None,
                                smi_params=None, macd_params=None):
    """
    Batch-calculate core indicators using pandas-ta-classic Strategy.
    Falls back to individual calls for indicators not supported by Strategy.

    Returns a dict of indicator name -> Series/DataFrame.
    """
    if ema_lengths is None:
        ema_lengths = [5, 9, 13, 21, 34, 50, 89, 200]
    if stoch_rsi_params is None:
        stoch_rsi_params = {"length": 14, "rsi_length": 14, "k": 3, "d": 3}
    if macd_params is None:
        macd_params = {"fast": 12, "slow": 26, "signal": 9}

    # Build Strategy for batch-able indicators
    ta_list = []
    for length in ema_lengths:
        ta_list.append({"kind": "ema", "length": length, "sma": False})
    ta_list.append({"kind": "rsi"})
    ta_list.append({"kind": "macd", "fast": macd_params["fast"],
                    "slow": macd_params["slow"], "signal": macd_params["signal"]})
    ta_list.append({"kind": "bbands", "length": 20, "std": 2})
    ta_list.append({"kind": "adx"})
    ta_list.append({"kind": "atr"})
    ta_list.append({"kind": "obv"})
    ta_list.append({"kind": "supertrend", "length": 10, "multiplier": 3})

    strategy = ta.Strategy(name="NSE_Scanner", ta=ta_list)
    df.ta.strategy(strategy, append=True)

    # Extract results from appended columns
    results = {}

    # EMAs
    for length in ema_lengths:
        col = f"EMA_{length}"
        if col in df.columns:
            results[f"ema_{length}"] = df[col].fillna(0)

    # RSI
    if "RSI_14" in df.columns:
        results["rsi"] = df["RSI_14"]

    # MACD
    macd_cols = [c for c in df.columns if c.startswith("MACD_") and not c.startswith("MACDh") and not c.startswith("MACDs")]
    macdh_cols = [c for c in df.columns if c.startswith("MACDh_")]
    macds_cols = [c for c in df.columns if c.startswith("MACDs_")]
    if macd_cols:
        results["macd_line"] = df[macd_cols[0]].fillna(0)
    if macdh_cols:
        results["macd_hist"] = df[macdh_cols[0]].fillna(0)
    if macds_cols:
        results["signal_line"] = df[macds_cols[0]].fillna(0)

    # BBands - compute width from BBL/BBM/BBU (library BBB is 100x scale)
    bbl_cols = [c for c in df.columns if c.startswith("BBL_")]
    bbm_cols = [c for c in df.columns if c.startswith("BBM_")]
    bbu_cols = [c for c in df.columns if c.startswith("BBU_")]
    if bbl_cols and bbm_cols and bbu_cols:
        mid_safe = df[bbm_cols[0]].replace(0, np.nan)
        results["bb_width"] = ((df[bbu_cols[0]] - df[bbl_cols[0]]) / mid_safe).fillna(0)

    # ADX
    adx_cols = [c for c in df.columns if c.startswith("ADX_")]
    if adx_cols:
        results["adx"] = df[adx_cols[0]].fillna(0)

    # ATR
    atr_cols = [c for c in df.columns if c.startswith("ATR")]
    if atr_cols:
        results["atr"] = df[atr_cols[0]]

    # OBV
    if "OBV" in df.columns:
        results["obv"] = df["OBV"]

    # Supertrend
    st_cols = [c for c in df.columns if c.startswith("SUPERT_") and not c.startswith("SUPERTd") and not c.startswith("SUPERTl") and not c.startswith("SUPERTs")]
    std_cols = [c for c in df.columns if c.startswith("SUPERTd_")]
    if st_cols:
        results["supertrend"] = df[st_cols[0]].fillna(0)
    if std_cols:
        results["st_dir"] = df[std_cols[0]].fillna(1)

    # StochRSI (individual call)
    results["stoch_rsi_k"] = calculate_stoch_rsi(df, **stoch_rsi_params)

    # SMI (manual - library version is incompatible)
    if smi_params is None:
        smi_params = {"length": 10, "smooth": 3}
    results["smi"] = calculate_smi(df, **smi_params)

    # VWAP (manual - avoids timezone warnings)
    results["vwap"] = calculate_vwap(df)

    return results


# ============================================================
# PRICE ACTION INDICATORS
# ============================================================

def detect_candlestick_patterns(df):
    """
    Detect major candlestick patterns. Returns dict with pattern scores.
    Score: +1 (bullish), -1 (bearish), 0 (no pattern).
    """
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body = abs(c - o)
    upper_wick = h - pd.concat([c, o], axis=1).max(axis=1)
    lower_wick = pd.concat([c, o], axis=1).min(axis=1) - l
    candle_range = h - l
    avg_body = body.rolling(20).mean()

    results = {}

    # Bullish/Bearish Engulfing
    prev_body = body.shift(1)
    bull_engulf = ((c > o) & (c.shift(1) < o.shift(1)) &
                   (c > o.shift(1)) & (o < c.shift(1)) &
                   (body > prev_body * 1.2))
    bear_engulf = ((c < o) & (c.shift(1) > o.shift(1)) &
                   (c < o.shift(1)) & (o > c.shift(1)) &
                   (body > prev_body * 1.2))
    results['engulfing'] = pd.Series(np.where(bull_engulf, 1, np.where(bear_engulf, -1, 0)), index=df.index).fillna(0).astype(int)

    # Hammer / Hanging Man
    small_body = body < (candle_range * 0.33)
    long_lower = lower_wick > (body * 2)
    short_upper = upper_wick < (body * 0.5)
    hammer_bull = small_body & long_lower & short_upper & (c > o)
    hammer_bear = small_body & long_lower & short_upper & (c < o)
    results['hammer'] = pd.Series(np.where(hammer_bull, 1, np.where(hammer_bear, -1, 0)), index=df.index).fillna(0).astype(int)

    # Doji (indecision)
    doji = (body < (candle_range * 0.1)) & (candle_range > 0)
    results['doji'] = pd.Series(np.where(doji, 1, 0), index=df.index).fillna(0).astype(int)

    # Morning Star / Evening Star (3-candle pattern)
    prev2_body = body.shift(2)
    morn_star = ((c.shift(2) < o.shift(2)) & (prev2_body > avg_body.shift(2)) &
                 (body.shift(1) < avg_body.shift(1) * 0.3) &
                 (c > o) & (body > avg_body))
    eve_star = ((c.shift(2) > o.shift(2)) & (prev2_body > avg_body.shift(2)) &
                (body.shift(1) < avg_body.shift(1) * 0.3) &
                (c < o) & (body > avg_body))
    results['star'] = pd.Series(np.where(morn_star, 1, np.where(eve_star, -1, 0)), index=df.index).fillna(0).astype(int)

    # Inside Bar (consolidation)
    inside = (h < h.shift(1)) & (l > l.shift(1))
    results['inside_bar'] = pd.Series(np.where(inside, 1, 0), index=df.index).fillna(0).astype(int)

    # Outside Bar (expansion)
    outside = (h > h.shift(1)) & (l < l.shift(1))
    outside_bull = outside & (c > o)
    outside_bear = outside & (c < o)
    results['outside_bar'] = pd.Series(np.where(outside_bull, 1, np.where(outside_bear, -1, 0)), index=df.index).fillna(0).astype(int)

    return results


def calculate_trend_structure(df, lookback=20):
    """
    Detect Higher Highs/Higher Lows (bullish) or Lower Highs/Lower Lows (bearish).
    """
    h, l = df['high'], df['low']

    swing_high = (h > h.shift(1)) & (h > h.shift(2)) & (h > h.shift(-1)) & (h > h.shift(-2))
    swing_low = (l < l.shift(1)) & (l < l.shift(2)) & (l < l.shift(-1)) & (l < l.shift(-2))

    sh_series = pd.Series(np.where(swing_high, h, np.nan), index=df.index).ffill()
    sl_series = pd.Series(np.where(swing_low, l, np.nan), index=df.index).ffill()

    prev_sh = sh_series.shift(lookback)
    prev_sl = sl_series.shift(lookback)

    hh = sh_series > prev_sh
    hl = sl_series > prev_sl
    lh = sh_series < prev_sh
    ll = sl_series < prev_sl

    bullish_structure = hh & hl
    bearish_structure = lh & ll
    structure = np.where(bullish_structure, 1, np.where(bearish_structure, -1, 0))

    return {
        'trend_structure': pd.Series(structure, index=df.index).fillna(0).astype(int),
        'swing_high': sh_series,
        'swing_low': sl_series,
    }


def calculate_breakout_levels(df, lookback=20):
    """
    Detect breakouts above resistance and breakdowns below support.
    """
    h, l, c = df['high'], df['low'], df['close']

    resistance = h.shift(1).rolling(lookback).max()
    support = l.shift(1).rolling(lookback).min()

    breakout_up = c > resistance
    breakout_down = c < support

    avg_vol = df['volume'].rolling(20).mean()
    vol_confirm = df['volume'] > avg_vol * 1.5

    strong_breakout = np.where(breakout_up & vol_confirm, 1,
                    np.where(breakout_down & vol_confirm, -1,
                    np.where(breakout_up, 0.5,
                    np.where(breakout_down, -0.5, 0))))

    return {
        'breakout': pd.Series(strong_breakout, index=df.index).fillna(0),
        'resistance': resistance,
        'support': support,
    }


# ============================================================
# MONEY FLOW INDICATORS
# ============================================================

def calculate_mfi(df, length=14):
    """Money Flow Index — volume-weighted RSI. Range 0-100."""
    if len(df) < length:
        return pd.Series(50, index=df.index)
    result = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=length)
    return result.fillna(50) if result is not None else pd.Series(50, index=df.index)


def calculate_cmf(df, length=20):
    """Chaikin Money Flow — buying/selling pressure. Range -1 to +1."""
    if len(df) < length:
        return pd.Series(0, index=df.index)
    mfm = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low']).replace(0, np.nan)
    mfv = mfm * df['volume']
    cmf = mfv.rolling(length).sum() / df['volume'].rolling(length).sum().replace(0, np.nan)
    return cmf.fillna(0)


def calculate_ad_line(df):
    """Accumulation/Distribution Line — cumulative money flow."""
    clv = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low']).replace(0, np.nan)
    ad = (clv * df['volume']).cumsum()
    return ad


def calculate_force_index(df, length=13):
    """Force Index — price change * volume. Shows conviction behind moves."""
    fi = (df['close'] - df['close'].shift(1)) * df['volume']
    return fi.ewm(span=length, adjust=False).mean().fillna(0)


def calculate_volume_profile_ratio(df, length=20):
    """Compare current volume vs average. Rising = accumulation."""
    vol_sma = df['volume'].rolling(length).mean()
    vol_sma_fast = df['volume'].rolling(5).mean()
    ratio = vol_sma_fast / vol_sma.replace(0, np.nan)
    return ratio.fillna(1)


def calculate_vwap_distance_pct(df):
    """Distance of price from VWAP as percentage."""
    vwap = calculate_vwap(df)
    dist = ((df['close'] - vwap) / vwap.replace(0, np.nan)) * 100
    return dist.fillna(0)


# ============================================================
# CONFLUENCE SCORING ENGINE
# ============================================================

def score_price_action(df, pos):
    """
    Price Action Group Score (0-100).
    Components: candlestick patterns, trend structure, breakouts, price position.
    """
    score = 0

    patterns = detect_candlestick_patterns(df)
    structure = calculate_trend_structure(df)
    breakout = calculate_breakout_levels(df)

    # Recent candlestick patterns (last 3 bars)
    for pat_name in ['engulfing', 'hammer', 'star', 'outside_bar']:
        recent = patterns[pat_name].iloc[max(0, pos-2):pos+1].sum()
        if recent > 0:
            score += 15
        elif recent < 0:
            score -= 15

    # Trend structure
    ts = structure['trend_structure'].iloc[pos]
    if ts == 1:
        score += 25
    elif ts == -1:
        score -= 10

    # Breakout
    bo = breakout['breakout'].iloc[pos]
    if bo >= 1:
        score += 25
    elif bo >= 0.5:
        score += 15
    elif bo <= -1:
        score -= 25
    elif bo <= -0.5:
        score -= 15

    # Price in range (above midpoint is bullish for trend)
    range_high = df['high'].rolling(20).max().iloc[pos]
    range_low = df['low'].rolling(20).min().iloc[pos]
    rng = range_high - range_low
    if rng > 0:
        pos_pct = (df['close'].iloc[pos] - range_low) / rng * 100
        if pos_pct > 75:
            score += 15
        elif pos_pct > 50:
            score += 8
        elif pos_pct < 25:
            score -= 10

    return max(0, min(100, score + 50))  # Normalize to 0-100, center at 50


def score_money_flow(df, pos):
    """
    Money Flow Group Score (0-100).
    Components: MFI, CMF, A/D Line slope, Force Index, Volume ratio, VWAP distance.
    """
    score = 0

    # MFI (0-100, >50 bullish, <50 bearish)
    mfi = calculate_mfi(df)
    mfi_val = mfi.iloc[pos]
    if mfi_val > 70:
        score += 20
    elif mfi_val > 55:
        score += 10
    elif mfi_val < 30:
        score -= 20
    elif mfi_val < 45:
        score -= 10

    # CMF (-1 to +1, positive = accumulation)
    cmf = calculate_cmf(df)
    cmf_val = cmf.iloc[pos]
    if cmf_val > 0.15:
        score += 20
    elif cmf_val > 0:
        score += 10
    elif cmf_val < -0.15:
        score -= 20
    elif cmf_val < 0:
        score -= 10

    # A/D Line slope (rising = accumulation)
    ad = calculate_ad_line(df)
    ad_slope = ad.iloc[pos] - ad.iloc[max(0, pos-5)]
    if ad_slope > 0:
        score += 15
    else:
        score -= 10

    # Force Index (positive = buying pressure)
    fi = calculate_force_index(df)
    fi_val = fi.iloc[pos]
    if fi_val > 0:
        score += 10
    else:
        score -= 10

    # Volume profile (rising volume = interest)
    vr = calculate_volume_profile_ratio(df)
    vr_val = vr.iloc[pos]
    if vr_val > 1.5:
        score += 15
    elif vr_val > 1.0:
        score += 5

    # VWAP distance (above = bullish)
    vwap_dist = calculate_vwap_distance_pct(df)
    vd = vwap_dist.iloc[pos]
    if vd > 0.5:
        score += 10
    elif vd < -0.5:
        score -= 10

    return max(0, min(100, score + 50))


def score_trend(df, pos, emas):
    """Trend Group Score (0-100). EMA alignment, ADX, Supertrend."""
    score = 0
    c = df['close'].iloc[pos]

    # EMA alignment (price > EMA9 > EMA21 > EMA50 > EMA200)
    e9 = emas[9].iloc[pos] if 9 in emas else 0
    e21 = emas[21].iloc[pos] if 21 in emas else 0
    e50 = emas[50].iloc[pos] if 50 in emas else 0
    e200 = emas[200].iloc[pos] if 200 in emas else 0

    if c > e9 > e21 > e50:
        score += 25
    elif c > e21 and e9 > e21:
        score += 15
    elif c < e9 < e21 < e50:
        score -= 25
    elif c < e21:
        score -= 15

    if c > e200:
        score += 10
    else:
        score -= 10

    # ADX (trend strength)
    adx = calculate_adx(df).iloc[pos]
    if adx > 30:
        score += 15
    elif adx > 20:
        score += 8

    # Supertrend
    _, st_dir = calculate_supertrend(df)
    if st_dir.iloc[pos] == 1:
        score += 10
    else:
        score -= 10

    return max(0, min(100, score + 50))


def score_momentum(df, pos):
    """Momentum Group Score (0-100). RSI, MACD, Stoch RSI, CCI."""
    score = 0

    # RSI
    rsi = calculate_rsi(df).iloc[pos]
    if 50 < rsi < 70:
        score += 20
    elif rsi >= 70:
        score -= 5
    elif rsi < 40:
        score -= 15
    elif rsi >= 40:
        score += 5

    # MACD histogram slope
    _, _, macd_hist = calculate_macd(df)
    macd_slope = macd_hist.iloc[pos] - macd_hist.iloc[max(0, pos-3)]
    if macd_hist.iloc[pos] > 0 and macd_slope > 0:
        score += 25
    elif macd_hist.iloc[pos] > 0:
        score += 15
    elif macd_hist.iloc[pos] < 0 and macd_slope < 0:
        score -= 25
    elif macd_hist.iloc[pos] < 0:
        score -= 10

    # Stoch RSI
    stoch = calculate_stoch_rsi(df).iloc[pos]
    if 50 < stoch < 80:
        score += 15
    elif stoch > 80:
        score -= 5
    elif stoch < 30:
        score -= 15

    # CCI (Commodity Channel Index)
    cci = ta.cci(df['high'], df['low'], df['close'], length=20)
    cci_val = cci.iloc[pos] if cci is not None else 0
    if 0 < cci_val < 150:
        score += 15
    elif cci_val > 200:
        score -= 10
    elif cci_val < -100:
        score -= 15

    return max(0, min(100, score + 50))


def score_volatility(df, pos):
    """Volatility Group Score (0-100). BBW squeeze, ATR expansion, range analysis."""
    score = 0

    # BB Width (squeeze = potential breakout)
    bbw = calculate_bb_width(df).iloc[pos]
    if bbw < 0.04:
        score += 20  # Squeeze — big move coming
    elif bbw < 0.06:
        score += 10
    elif bbw > 0.10:
        score -= 10  # Expanded — move may be over

    # ATR trend (rising = increasing activity)
    atr = calculate_atr(df)
    atr_now = atr.iloc[pos]
    atr_prev = atr.iloc[max(0, pos-5)]
    if atr_now > atr_prev * 1.1:
        score += 15  # Volatility expanding
    elif atr_now < atr_prev * 0.9:
        score += 5   # Volatility contracting (setup forming)

    # Price action within ATR bands
    c = df['close'].iloc[pos]
    atr_pct = (atr_now / c * 100) if c > 0 else 0
    if 1 < atr_pct < 3:
        score += 15  # Healthy volatility
    elif atr_pct > 5:
        score -= 10  # Too volatile

    return max(0, min(100, score + 50))


def calculate_confluence_scores(df, pos, emas):
    """
    Master confluence function. Returns dict with all 5 group scores + combined.
    """
    pa_score = score_price_action(df, pos)
    mf_score = score_money_flow(df, pos)
    trend_score = score_trend(df, pos, emas)
    momentum_score = score_momentum(df, pos)
    vol_score = score_volatility(df, pos)

    # Weighted confluence (trend + momentum most important for trading)
    confluence = (
        pa_score * 0.20 +
        mf_score * 0.20 +
        trend_score * 0.25 +
        momentum_score * 0.25 +
        vol_score * 0.10
    )

    # Signal from confluence
    if confluence >= 75:
        signal = "STRONG BUY"
    elif confluence >= 65:
        signal = "BUY"
    elif confluence >= 55:
        signal = "WEAK BUY"
    elif confluence <= 25:
        signal = "STRONG SELL"
    elif confluence <= 35:
        signal = "SELL"
    elif confluence <= 45:
        signal = "WEAK SELL"
    else:
        signal = "NEUTRAL"

    return {
        'price_action': round(pa_score, 1),
        'money_flow': round(mf_score, 1),
        'trend_score': round(trend_score, 1),
        'momentum': round(momentum_score, 1),
        'volatility': round(vol_score, 1),
        'confluence': round(confluence, 1),
        'confluence_signal': signal,
    }


def get_confluence_details(df, pos, emas):
    """Get detailed breakdown of each confluence component for display."""
    pa = score_price_action_breakdown(df, pos)
    mf = score_money_flow_breakdown(df, pos)
    return pa, mf


def score_price_action_breakdown(df, pos):
    """Detailed price action breakdown for display."""
    patterns = detect_candlestick_patterns(df)
    structure = calculate_trend_structure(df)
    breakout = calculate_breakout_levels(df)

    details = {}
    for name in ['engulfing', 'hammer', 'doji', 'star', 'inside_bar', 'outside_bar']:
        val = patterns[name].iloc[pos]
        if val == 1:
            details[name] = "Bullish" if name != 'doji' else "Indecision"
        elif val == -1:
            details[name] = "Bearish"
        else:
            details[name] = "—"

    ts = structure['trend_structure'].iloc[pos]
    details['structure'] = {1: "HH/HL (Bull)", -1: "LH/LL (Bear)", 0: "Neutral"}[ts]

    bo = breakout['breakout'].iloc[pos]
    if bo >= 1:
        details['breakout'] = "Strong Breakout"
    elif bo >= 0.5:
        details['breakout'] = "Breakout"
    elif bo <= -1:
        details['breakout'] = "Strong Breakdown"
    elif bo <= -0.5:
        details['breakout'] = "Breakdown"
    else:
        details['breakout'] = "—"

    return details


def score_money_flow_breakdown(df, pos):
    """Detailed money flow breakdown for display."""
    mfi_val = calculate_mfi(df).iloc[pos]
    cmf_val = calculate_cmf(df).iloc[pos]
    fi_val = calculate_force_index(df).iloc[pos]
    vr_val = calculate_volume_profile_ratio(df).iloc[pos]
    ad = calculate_ad_line(df)
    ad_slope = ad.iloc[pos] - ad.iloc[max(0, pos-5)]

    return {
        'MFI': round(mfi_val, 1),
        'CMF': round(cmf_val, 3),
        'A/D': "Rising" if ad_slope > 0 else "Falling",
        'Force': "Bullish" if fi_val > 0 else "Bearish",
        'Vol Ratio': round(vr_val, 2),
    }


def calculate_cpr(df, daily_df=None):
    """
    Calculate Central Pivot Range (CPR) with ATR-Normalized Width + Support/Resistance levels.

    Uses DAILY OHLC for accurate CPR levels (not aggregated intraday candles).
    If daily_df is provided, uses it for prev day OHLC. Otherwise falls back to aggregating from df.

    Returns DataFrame with: CPR_PP, CPR_BC, CPR_TC, CPR_Width, CPR_ATR, CPR_ATR_Ratio, CPR_Type,
                            CPR_R1, CPR_R2, CPR_R3, CPR_S1, CPR_S2, CPR_S3

    Formulas (from previous day's H/L/C):
        PP = (H + L + C) / 3
        BC = (H + L) / 2
        TC = 2 * PP - BC
        Width = abs(TC - BC)
        R1 = 2 * PP - L
        R2 = PP + (H - L)
        R3 = H + 2 * (PP - L)
        S1 = 2 * PP - H
        S2 = PP - (H - L)
        S3 = L - 2 * (H - PP)
        ATR Ratio = Width / ATR(14)

    ATR-Normalized Classification:
        < 0.15  : EXTREME NARROW
        0.15-0.30: VERY NARROW
        0.30-0.50: NARROW
        0.50-1.00: NORMAL
        1.00-1.50: SLIGHTLY WIDE
        1.50-2.00: WIDE
        > 2.00  : VERY WIDE
    """
    cpr_pp = pd.Series(np.nan, index=df.index)
    cpr_bc = pd.Series(np.nan, index=df.index)
    cpr_tc = pd.Series(np.nan, index=df.index)
    cpr_width = pd.Series(np.nan, index=df.index)
    cpr_atr = pd.Series(np.nan, index=df.index)
    cpr_atr_ratio = pd.Series(np.nan, index=df.index)
    cpr_type = pd.Series('', index=df.index)
    cpr_r1 = pd.Series(np.nan, index=df.index)
    cpr_r2 = pd.Series(np.nan, index=df.index)
    cpr_r3 = pd.Series(np.nan, index=df.index)
    cpr_s1 = pd.Series(np.nan, index=df.index)
    cpr_s2 = pd.Series(np.nan, index=df.index)
    cpr_s3 = pd.Series(np.nan, index=df.index)

    # Calculate ATR(14) for the entire series
    atr_series = calculate_atr(df, length=14)

    # Get daily OHLC — prefer daily_df (accurate) over aggregating intraday
    dates = df.index.date
    unique_dates = sorted(set(dates))

    # Build daily OHLC lookup
    daily_ohlc = {}
    if daily_df is not None and not daily_df.empty:
        for dt in daily_df.index:
            d = dt.date() if hasattr(dt, 'date') else dt
            daily_ohlc[d] = {
                'high': float(daily_df.loc[dt, 'high']),
                'low': float(daily_df.loc[dt, 'low']),
                'close': float(daily_df.loc[dt, 'close']),
            }
    else:
        # Fallback: aggregate from intraday
        for d in unique_dates:
            mask = dates == d
            day_data = df[mask]
            if not day_data.empty:
                daily_ohlc[d] = {
                    'high': float(day_data['high'].max()),
                    'low': float(day_data['low'].min()),
                    'close': float(day_data['close'].iloc[-1]),
                }

    for i, d in enumerate(unique_dates):
        if i == 0:
            continue  # No previous day for first day

        prev_d = unique_dates[i - 1]
        if prev_d not in daily_ohlc:
            continue

        prev = daily_ohlc[prev_d]
        prev_high = prev['high']
        prev_low = prev['low']
        prev_close = prev['close']

        # CPR formulas (Zerodha method: round PP to 1 decimal first, then compute TC from rounded PP)
        pp = round((prev_high + prev_low + prev_close) / 3, 1)
        bc = round((prev_high + prev_low) / 2, 2)
        tc = round((2 * pp) - bc, 2)
        width = abs(tc - bc)

        # Support/Resistance levels (using Zerodha-rounded PP)
        r1 = round(2 * pp - prev_low, 2)
        r2 = round(pp + (prev_high - prev_low), 2)
        r3 = round(pp + 2 * (prev_high - prev_low), 2)
        s1 = round(2 * pp - prev_high, 2)
        s2 = round(pp - (prev_high - prev_low), 2)
        s3 = round(pp - 2 * (prev_high - prev_low), 2)

        # ATR for current day
        curr_mask = dates == d
        curr_atr = atr_series[curr_mask]
        atr_val = curr_atr.iloc[-1] if not curr_atr.empty and not pd.isna(curr_atr.iloc[-1]) else 0
        atr_ratio = width / atr_val if atr_val > 0 else 0

        # Classification
        if atr_ratio < 0.15:
            cpr_class = "EXTREME NARROW"
        elif atr_ratio < 0.30:
            cpr_class = "VERY NARROW"
        elif atr_ratio < 0.50:
            cpr_class = "NARROW"
        elif atr_ratio < 1.00:
            cpr_class = "NORMAL"
        elif atr_ratio < 1.50:
            cpr_class = "SLIGHTLY WIDE"
        elif atr_ratio < 2.00:
            cpr_class = "WIDE"
        else:
            cpr_class = "VERY WIDE"

        cpr_pp[curr_mask] = round(pp, 2)
        cpr_bc[curr_mask] = round(bc, 2)
        cpr_tc[curr_mask] = round(tc, 2)
        cpr_width[curr_mask] = round(width, 2)
        cpr_atr[curr_mask] = round(atr_val, 2)
        cpr_atr_ratio[curr_mask] = round(atr_ratio, 3)
        cpr_type[curr_mask] = cpr_class
        cpr_r1[curr_mask] = round(r1, 2)
        cpr_r2[curr_mask] = round(r2, 2)
        cpr_r3[curr_mask] = round(r3, 2)
        cpr_s1[curr_mask] = round(s1, 2)
        cpr_s2[curr_mask] = round(s2, 2)
        cpr_s3[curr_mask] = round(s3, 2)

    return pd.DataFrame({
        'CPR_PP': cpr_pp, 'CPR_BC': cpr_bc, 'CPR_TC': cpr_tc,
        'CPR_Width': cpr_width, 'CPR_ATR': cpr_atr,
        'CPR_ATR_Ratio': cpr_atr_ratio, 'CPR_Type': cpr_type,
        'CPR_R1': cpr_r1, 'CPR_R2': cpr_r2, 'CPR_R3': cpr_r3,
        'CPR_S1': cpr_s1, 'CPR_S2': cpr_s2, 'CPR_S3': cpr_s3,
    }, index=df.index)
