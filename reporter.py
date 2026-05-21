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


def _cpr_stock_line(row):
    """Formats a single CPR stock line for Telegram."""
    name = row['Stock Name']
    close = row['Close']
    cpr_type = row.get('CPR_Type', '')
    ratio = row.get('CPR_ATR_Ratio', 0)
    position = row.get('CPR_Position', '')
    vol = row.get('Volume', 0)

    # Position icon
    if 'Bullish' in str(position):
        pos_icon = '🟢'
    elif 'Bearish' in str(position):
        pos_icon = '🔴'
    else:
        pos_icon = '⚪'

    try:
        ratio_str = f"{float(ratio):.2f}" if ratio and str(ratio) != 'nan' else "N/A"
    except (ValueError, TypeError):
        ratio_str = "N/A"
    line = f"{pos_icon} *{name}* ₹{close} | {cpr_type} | ATR:{ratio_str}"
    line += f" | Vol:{format_volume(vol)}"

    # Add CPR levels
    pp = row.get('CPR_PP', '')
    bc = row.get('CPR_BC', '')
    tc = row.get('CPR_TC', '')
    if pp and bc and tc:
        try:
            line += f"\n   PP:₹{float(pp):.1f} BC:₹{float(bc):.1f} TC:₹{float(tc):.1f}"
        except (ValueError, TypeError):
            pass

    # Add R1/S1 if available
    r1 = row.get('CPR_R1', '')
    s1 = row.get('CPR_S1', '')
    if r1 and s1:
        try:
            line += f" | R1:₹{float(r1):.1f} S1:₹{float(s1):.1f}"
        except (ValueError, TypeError):
            pass

    return line


def generate_report(df, universe, timeframe):
    """
    CPR-Only Reporter — generates Telegram messages from CPR scan results.
    Returns: List of message strings.
    """
    if df.empty:
        return [(
            f"ℹ️ *CPR Scan Update*\n\n"
            f"📊 *Universe:* {universe}\n"
            f"⏰ *Timeframe:* {timeframe}\n"
            f"⚠️ No matches found.\n"
            f"📅 {datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S')} IST"
        )]

    # Deduplicate: keep latest candle per stock
    df_work = df.copy()
    unique_df = df_work.sort_values('Signal Time', ascending=False).drop_duplicates(subset='Stock Name')

    # Ensure numeric columns are numeric (defensive — scanner should already handle this)
    for col in ['CPR_ATR_Ratio', 'CPR_PP', 'CPR_BC', 'CPR_TC', 'CPR_Width', 'CPR_ATR',
                'CPR_R1', 'CPR_R2', 'CPR_R3', 'CPR_S1', 'CPR_S2', 'CPR_S3',
                'Prev_Open', 'Prev_High', 'Prev_Low', 'Prev_Close', 'Volume', 'Close']:
        if col in unique_df.columns:
            unique_df[col] = pd.to_numeric(unique_df[col], errors='coerce')

    total_found = len(df)
    unique_stocks = len(unique_df)
    now_ist = datetime.now(IST).strftime('%d-%m-%Y %H:%M:%S')

    all_chunks = []

    # ============================================================
    # PART 1: HEADER + NARROW CPR (Breakout Candidates)
    # ============================================================
    p1_lines = [
        f"📊 *CPR Scanner* | *{universe}*",
        f"----------------------------------------",
        f"✅ *Signals:* {total_found} ({unique_stocks} stocks) | *TF:* {timeframe}",
        f"🕐 *Time:* {now_ist} IST",
        f"----------------------------------------",
    ]

    # CPR Type distribution
    if 'CPR_Type' in unique_df.columns:
        type_counts = unique_df['CPR_Type'].value_counts()
        type_line = " | ".join([f"{t}: {c}" for t, c in type_counts.items()])
        p1_lines.append(f"📈 *CPR Types:* {type_line}")
        p1_lines.append(f"----------------------------------------")

    # Top 10 Narrowest CPR — best breakout candidates
    narrow_df = unique_df[unique_df['CPR_ATR_Ratio'].notna() & (unique_df['CPR_ATR_Ratio'] > 0)]
    narrow_df = narrow_df.nsmallest(10, 'CPR_ATR_Ratio')

    if not narrow_df.empty:
        p1_lines.append(f"🔥 *TOP NARROW CPR — Breakout Candidates*")
        p1_lines.append(f"_Lowest ATR ratio = tightest range = biggest potential move_")
        for _, row in narrow_df.iterrows():
            p1_lines.append(_cpr_stock_line(row))
        p1_lines.append(f"----------------------------------------")

    all_chunks.extend(split_list_to_chunks(p1_lines, 3800))

    # ============================================================
    # PART 2: ABOVE TC (Bullish)
    # ============================================================
    p2_lines = []
    bull_df = unique_df[unique_df['CPR_Position'].str.contains('Bullish', na=False)]

    if not bull_df.empty:
        # Sort by ATR ratio (narrowest first)
        bull_df = bull_df[bull_df['CPR_ATR_Ratio'].notna()].nsmallest(10, 'CPR_ATR_Ratio')
        p2_lines.append(f"🟢 *ABOVE TC — Bullish Positions*")
        p2_lines.append(f"_Price above Top Central — bullish bias_")
        for _, row in bull_df.iterrows():
            p2_lines.append(_cpr_stock_line(row))
        p2_lines.append(f"----------------------------------------")

    if p2_lines:
        all_chunks.extend(split_list_to_chunks(p2_lines, 3800))

    # ============================================================
    # PART 3: BELOW BC (Bearish)
    # ============================================================
    p3_lines = []
    bear_df = unique_df[unique_df['CPR_Position'].str.contains('Bearish', na=False)]

    if not bear_df.empty:
        bear_df = bear_df[bear_df['CPR_ATR_Ratio'].notna()].nsmallest(10, 'CPR_ATR_Ratio')
        p3_lines.append(f"🔴 *BELOW BC — Bearish Positions*")
        p3_lines.append(f"_Price below Bottom Central — bearish bias_")
        for _, row in bear_df.iterrows():
            p3_lines.append(_cpr_stock_line(row))
        p3_lines.append(f"----------------------------------------")

    if p3_lines:
        all_chunks.extend(split_list_to_chunks(p3_lines, 3800))

    # ============================================================
    # PART 4: INSIDE CPR (Neutral / Consolidation)
    # ============================================================
    p4_lines = []
    neutral_df = unique_df[unique_df['CPR_Position'].str.contains('Neutral', na=False)]

    if not neutral_df.empty:
        neutral_df = neutral_df[neutral_df['CPR_ATR_Ratio'].notna()].nsmallest(10, 'CPR_ATR_Ratio')
        p4_lines.append(f"⚪ *INSIDE CPR — Consolidation*")
        p4_lines.append(f"_Price within CPR range — wait for breakout_")
        for _, row in neutral_df.iterrows():
            p4_lines.append(_cpr_stock_line(row))
        p4_lines.append(f"----------------------------------------")

    if p4_lines:
        all_chunks.extend(split_list_to_chunks(p4_lines, 3800))

    return all_chunks
