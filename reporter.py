import pandas as pd
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')


def format_volume(vol):
    """Formats large volumes into k/M suffixes for readability."""
    if vol >= 1_000_000:
        return f"{vol/1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"{vol/1_000:.0f}k"
    return str(int(vol))


def get_market_mood(df):
    """Calculates market mood from score distribution."""
    if df.empty:
        return "⚖️ NEUTRAL"
    avg_ign = df['ignition_score'].mean() if 'ignition_score' in df.columns else 0
    avg_intra = df['intraday_score'].mean() if 'intraday_score' in df.columns else 0
    if avg_ign > 50 and avg_intra > 50:
        return "🔥 STRONG MOMENTUM (Multiple ignition + intraday signals)"
    elif avg_ign > 40 or avg_intra > 40:
        return "✅ BULLISH (Healthy momentum building)"
    return "⚖️ NEUTRAL (Selective opportunities only)"


def split_list_to_chunks(lines, limit):
    """Groups a list of lines into chunks each under the specified character limit."""
    chunks = []
    current_chunk = []
    current_length = 0
    for line in lines:
        line_len = len(line) + 1
        if current_length + line_len > limit:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_length = line_len
        else:
            current_chunk.append(line)
            current_length += line_len
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


def _format_stock_line(row, score_field, score_max, show_entry=False):
    """Formats a single stock line for Telegram with overextension warning."""
    name = row['Stock Name']
    ltp = row['LTP']
    sc_val = int(row.get(score_field, 0))
    rsi_val = row.get('RSI', 0)
    rvol = row.get('RVOL', 0)
    ext = row.get('Overext_Flag', '')
    dist = row.get('Dist_EMA21', 0)

    line = f"👉 *{name}* ₹{ltp} | {score_field.split('_')[0].upper()}: {sc_val}/{score_max}"
    line += f" | RSI:{rsi_val:.0f} RVOL:{rvol:.1f}x"

    # Show decay warning if stock is fading from recent highs
    decay = row.get('decay_flag', '')
    if decay:
        details = row.get('decay_details', '')
        line += f" | {decay}"
        if details:
            line += f" ({details})"
    elif ext:
        line += f" | {ext} ({dist:+.1f}%)"

    if show_entry and 'Entry_Zone' in row and not decay:
        line += f"\n   📍 Entry:₹{row['Entry_Zone']} SL:₹{row['Stop_Loss']} T1:₹{row['Target_1']} T2:₹{row['Target_2']}"

    return line


def generate_report(df, universe, timeframe):
    """
    NSE Market Analyst v3.0 - 3-Score System Reporter.
    Returns: List of message strings formatted for Telegram.
    """
    if df.empty:
        return [(
            f"ℹ️ *NSE Market Scan Update*\n\n"
            f"📊 *Universe:* {universe}\n"
            f"⏰ *Timeframe:* {timeframe}\n"
            f"⚠️ No matches found.\n"
            f"📅 {datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S')} IST"
        )]

    # Deduplicate — keep the BEST candle per stock based on signal type
    # For FRESH signals: keep highest ignition score (earliest detection moment)
    # For other signals: keep latest candle (most recent state)
    df_work = df.copy()
    df_work['_max_score'] = df_work[['ignition_score', 'intraday_score', 'swing_score']].max(axis=1)

    # Split into FRESH and non-FRESH
    fresh_mask = df_work['signal_type'].str.contains('FRESH', na=False)
    fresh_df = df_work[fresh_mask].sort_values('ignition_score', ascending=False).drop_duplicates(subset='Stock Name')
    other_df = df_work[~fresh_mask].sort_values('Signal Time', ascending=False).drop_duplicates(subset='Stock Name')

    # Combine: FRESH stocks use best ignition, others use latest candle
    # If a stock appears in both, prefer FRESH (early detection is priority)
    fresh_stocks = set(fresh_df['Stock Name'])
    other_filtered = other_df[~other_df['Stock Name'].isin(fresh_stocks)]
    unique_df = pd.concat([fresh_df, other_filtered]).copy()

    total_found = len(df)
    now_ist = datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S')
    mood = get_market_mood(unique_df)

    all_chunks = []

    # Filter: exclude decaying stocks from positive signal sections
    is_decay = unique_df.get('decay_flag', pd.Series('', index=unique_df.index)).str.len() > 0
    clean_df = unique_df[~is_decay]  # Stocks NOT in decay
    decay_df = unique_df[is_decay]   # Stocks IN decay

    # ============================================================
    # PART 1: HEADER + EARLY DETECTION (FRESH) + DUAL OPPORTUNITIES
    # ============================================================
    p1_lines = [
        f"🚀 *NSE Market Analysis v3.0* | 📊 *{universe}*",
        f"----------------------------------------",
        f"🏁 *MOOD:* _{mood}_",
        f"✅ *Signals:* {total_found} | *TF:* {timeframe} | _{now_ist}_",
        f"----------------------------------------",
    ]

    # 🚀 FRESH SIGNALS — EARLIEST detection, stocks just starting to move
    # These are the highest-priority for 1h timeframe: momentum birth, not overbought
    fresh_df = clean_df[
        (clean_df['signal_type'].str.contains('FRESH', na=False)) |
        ((clean_df['ignition_score'] >= 45) & (clean_df['RSI'] < 65) & (clean_df['Dist_EMA21'] < 5))
    ].nlargest(5, 'ignition_score')

    if not fresh_df.empty:
        p1_lines.append(f"🚀 *FRESH SIGNALS — Early Detection (1h)*")
        p1_lines.append(f"_Stocks just starting momentum — NOT overbought_")
        for _, row in fresh_df.iterrows():
            ign = int(row.get('ignition_score', 0))
            name = row['Stock Name']
            ltp = row['LTP']
            rsi_val = row.get('RSI', 0)
            rvol = row.get('RVOL', 0)
            d21 = row.get('Dist_EMA21', 0)
            mh_slope = row.get('MACD_Hist_Slope', 0)
            line = f"👉 *{name}* ₹{ltp} | IGN:{ign} | RSI:{rsi_val:.0f} RVOL:{rvol:.1f}x"
            line += f" | EMA21:{d21:+.1f}%"
            if mh_slope > 0:
                line += f" | MACD↑"
            decay = row.get('decay_flag', '')
            if decay:
                line += f" | {decay}"
            if 'Entry_Zone' in row and not decay:
                line += f"\n   📍 Entry:₹{row['Entry_Zone']} SL:₹{row['Stop_Loss']} T1:₹{row['Target_1']} T2:₹{row['Target_2']}"
            p1_lines.append(line)
        p1_lines.append(f"----------------------------------------")

    # 🔥⚡ DUAL OPPORTUNITIES — Stocks with BOTH intraday AND swing potential
    dual_df = clean_df[
        (clean_df['signal_type'].str.contains('DUAL', na=False)) |
        ((clean_df['intraday_score'] >= 55) & (clean_df['swing_score'] >= 55))
    ].nlargest(5, 'ignition_score')

    if not dual_df.empty:
        p1_lines.append(f"🔥⚡ *DUAL OPPORTUNITIES — Intraday + Swing*")
        p1_lines.append(f"_Best picks: active momentum AND multi-day setup building_")
        for _, row in dual_df.iterrows():
            intra = int(row.get('intraday_score', 0))
            sw = int(row.get('swing_score', 0))
            ign = int(row.get('ignition_score', 0))
            name = row['Stock Name']
            ltp = row['LTP']
            rsi_val = row.get('RSI', 0)
            rvol = row.get('RVOL', 0)
            line = f"👉 *{name}* ₹{ltp} | IGN:{ign} INTRA:{intra} SW:{sw}"
            line += f" | RSI:{rsi_val:.0f} RVOL:{rvol:.1f}x"
            decay = row.get('decay_flag', '')
            if decay:
                line += f" | {decay}"
            if 'Entry_Zone' in row and not decay:
                line += f"\n   📍 Entry:₹{row['Entry_Zone']} SL:₹{row['Stop_Loss']} T1:₹{row['Target_1']} T2:₹{row['Target_2']}"
            p1_lines.append(line)
        p1_lines.append(f"----------------------------------------")

    # 🔥 IGNITION ALERTS — Early trend catches (exclude fading stocks)
    ign_df = clean_df[(clean_df['ignition_score'] >= 50) & (clean_df['RVOL'] >= 0.8)].nlargest(5, 'ignition_score')
    if not ign_df.empty:
        p1_lines.append(f"🔥 *IGNITION ALERTS — Trend Birth Detection*")
        p1_lines.append(f"_Catching momentum shift BEFORE overbought_")
        for _, row in ign_df.iterrows():
            p1_lines.append(_format_stock_line(row, 'ignition_score', 100, show_entry=True))
        p1_lines.append(f"----------------------------------------")

    all_chunks.extend(split_list_to_chunks(p1_lines, 3800))

    # ============================================================
    # PART 2: INTRADAY PLAYS
    # ============================================================
    p2_lines = []
    intra_df = clean_df[(clean_df['intraday_score'] >= 55) & (clean_df['RVOL'] >= 0.8)].nlargest(5, 'intraday_score')
    if not intra_df.empty:
        p2_lines.append(f"⚡ *INTRADAY PLAYS — Ride Today's Move*")
        p2_lines.append(f"_Active momentum with room to run_")
        for _, row in intra_df.iterrows():
            p2_lines.append(_format_stock_line(row, 'intraday_score', 100, show_entry=True))
        p2_lines.append(f"----------------------------------------")

    # Overextension warnings
    ext_df = unique_df[unique_df['Overext_Flag'] != ''].nlargest(3, 'Dist_EMA21')
    if not ext_df.empty:
        p2_lines.append(f"⚠️ *OVEREXTENSION ALERTS — DO NOT CHASE*")
        for _, row in ext_df.iterrows():
            p2_lines.append(f"👉 {row['Overext_Flag']} *{row['Stock Name']}* ({row['Dist_EMA21']:+.1f}% from EMA21)")
        p2_lines.append(f"----------------------------------------")

    if p2_lines:
        all_chunks.extend(split_list_to_chunks(p2_lines, 3800))

    # ============================================================
    # PART 3: SWING SETUPS
    # ============================================================
    p3_lines = []
    swing_df = clean_df[(clean_df['swing_score'] >= 55) & (clean_df['RVOL'] >= 0.6)].nlargest(5, 'swing_score')
    if not swing_df.empty:
        p3_lines.append(f"🌊 *SWING SETUPS — Multi-Day Builders*")
        p3_lines.append(f"_Accumulation patterns for 2-10 day holds_")
        for _, row in swing_df.iterrows():
            bbw = row.get('BBW', 0)
            squeeze_icon = " 🌀SQZ" if bbw <= 0.04 else ""
            rs = row.get('Rel Strength', 0)
            line = _format_stock_line(row, 'swing_score', 100, show_entry=True)
            line += f"{squeeze_icon} RS:{rs:+.1f}"
            p3_lines.append(line)
        p3_lines.append(f"----------------------------------------")

    if p3_lines:
        all_chunks.extend(split_list_to_chunks(p3_lines, 3800))

    # ============================================================
    # PART 3b: FADING / DISTRIBUTION ALERTS
    # ============================================================
    if not decay_df.empty:
        pf_lines = []
        pf_lines.append(f"📉 *FADING/DISTRIBUTION — DO NOT BUY*")
        pf_lines.append(f"_Stocks falling from recent highs — avoid catching falling knives_")
        decay_ranked = decay_df.nlargest(5, 'decay_penalty')
        for _, row in decay_ranked.iterrows():
            name = row['Stock Name']
            dp = int(row.get('decay_penalty', 0))
            flag = row.get('decay_flag', '')
            details = row.get('decay_details', '')
            rsi_val = row.get('RSI', 0)
            pf_lines.append(f"👉 {flag} *{name}* ₹{row['LTP']} | Penalty:-{dp} | RSI:{rsi_val:.0f} | {details}")
        pf_lines.append(f"----------------------------------------")
        all_chunks.extend(split_list_to_chunks(pf_lines, 3800))

    # ============================================================
    # PART 3c: EMA CROSSOVER SIGNALS
    # ============================================================
    cross_lines = []
    bull_entries = []
    bear_entries = []

    # Max bars_since to consider a crossover "recent" enough to report
    CROSS_RECENCY_MAX = 3

    for _, row in unique_df.iterrows():
        name = row['Stock Name']
        ltp = row['LTP']

        # Bullish crossovers
        b13x34 = row.get('ema13x34_bull_bars', -1)
        b13x34_t = row.get('ema13x34_bull_time', '')
        if isinstance(b13x34, (int, float)) and 0 <= b13x34 <= CROSS_RECENCY_MAX and b13x34_t:
            bull_entries.append((name, ltp, b13x34_t, '13×34', int(b13x34)))

        b34x89 = row.get('ema34x89_bull_bars', -1)
        b34x89_t = row.get('ema34x89_bull_time', '')
        if isinstance(b34x89, (int, float)) and 0 <= b34x89 <= CROSS_RECENCY_MAX and b34x89_t:
            bull_entries.append((name, ltp, b34x89_t, '34×89', int(b34x89)))

        # Bearish crossovers
        br13x34 = row.get('ema13x34_bear_bars', -1)
        br13x34_t = row.get('ema13x34_bear_time', '')
        if isinstance(br13x34, (int, float)) and 0 <= br13x34 <= CROSS_RECENCY_MAX and br13x34_t:
            bear_entries.append((name, ltp, br13x34_t, '13×34', int(br13x34)))

        br34x89 = row.get('ema34x89_bear_bars', -1)
        br34x89_t = row.get('ema34x89_bear_time', '')
        if isinstance(br34x89, (int, float)) and 0 <= br34x89 <= CROSS_RECENCY_MAX and br34x89_t:
            bear_entries.append((name, ltp, br34x89_t, '34×89', int(br34x89)))

    # Sort by recency (most recent crossover first)
    bull_entries.sort(key=lambda x: x[4])
    bear_entries.sort(key=lambda x: x[4])

    if bull_entries or bear_entries:
        cross_lines.append(f"📊 *EMA CROSSOVER SIGNALS*")
        cross_lines.append(f"_Recent EMA crossovers (last {CROSS_RECENCY_MAX} bars)_")
        cross_lines.append(f"----------------------------------------")

        if bull_entries:
            cross_lines.append(f"✅ *BULLISH CROSSOVERS*")
            for name, ltp, ctime, ctype, bars in bull_entries[:5]:
                freshness = "🔥" if bars <= 1 else "⚡" if bars <= 3 else "📌"
                cross_lines.append(f"{freshness} *{name}* ₹{ltp} | {ctype} | {ctime} | {bars}bar ago")
            cross_lines.append(f"----------------------------------------")

        if bear_entries:
            cross_lines.append(f"🔴 *BEARISH CROSSOVERS*")
            for name, ltp, ctime, ctype, bars in bear_entries[:5]:
                cross_lines.append(f"⚠️ *{name}* ₹{ltp} | {ctype} | {ctime} | {bars}bar ago")
            cross_lines.append(f"----------------------------------------")

        all_chunks.extend(split_list_to_chunks(cross_lines, 3800))

    # ============================================================
    # PART 4: POWERHOUSE (LEGACY 10-PT) + TOP RANKINGS
    # ============================================================
    p4_lines = []

    # Legacy Powerhouse
    if 'score' in unique_df.columns:
        power_df = unique_df[unique_df['score'] >= 8].nlargest(5, 'score')
        if not power_df.empty:
            p4_lines.append(f"🎯 *POWERHOUSE — Legacy 10-PT Confluence*")
            for _, row in power_df.iterrows():
                ext = f" {row['Overext_Flag']}" if row.get('Overext_Flag') else ""
                p4_lines.append(f"🔥 *{row['Stock Name']}* | Score: {int(row['score'])}/10{ext}")
            p4_lines.append(f"----------------------------------------")

    # Top Volume
    top_vol = unique_df.nlargest(3, 'Volume')
    if not top_vol.empty:
        vol_str = ', '.join([f"{r['Stock Name']} ({format_volume(r['Volume'])})" for _, r in top_vol.iterrows()])
        p4_lines.append(f"💎 *Top Vol:* {vol_str}")

    # Top RVOL (institutional flow)
    top_rvol = unique_df[unique_df['RVOL'] >= 2.0].nlargest(3, 'RVOL')
    if not top_rvol.empty:
        rvol_str = ', '.join([f"{r['Stock Name']} ({r['RVOL']:.1f}x)" for _, r in top_rvol.iterrows()])
        p4_lines.append(f"🏛️ *Institutional RVOL:* {rvol_str}")

    # Top Relative Strength
    top_rs = unique_df.nlargest(3, 'Rel Strength')
    if not top_rs.empty:
        rs_str = ', '.join([f"{r['Stock Name']} ({r['Rel Strength']:+.1f})" for _, r in top_rs.iterrows()])
        p4_lines.append(f"💪 *Top RS vs Nifty:* {rs_str}")

    if p4_lines:
        all_chunks.extend(split_list_to_chunks(p4_lines, 3800))

    return all_chunks
