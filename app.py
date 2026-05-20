import streamlit as st
import pandas as pd
import scanner
import data_loader
import pytz
import logging
import time
from datetime import datetime

# --- LOG CAPTURE FOR UI ---
log_lines = []

class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        log_lines.append(self.format(record))

# Install handler exactly once per process (avoids duplicate handlers on Streamlit reruns)
_LOG_HANDLER_INSTALLED = "_cpr_log_handler_installed"
if not getattr(logging.getLogger('scanner'), _LOG_HANDLER_INSTALLED, False):
    log_handler = StreamlitLogHandler()
    log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    log_handler.setLevel(logging.INFO)
    for name in ['scanner', 'data_loader']:
        lg = logging.getLogger(name)
        lg.addHandler(log_handler)
    setattr(logging.getLogger('scanner'), _LOG_HANDLER_INSTALLED, True)

# --- UI CONFIGURATION ---
st.set_page_config(page_title="NSE CPR Scanner", layout="wide", page_icon="📈")

hide_st_style = '''
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {display: none !important;}
[data-testid="stToolbar"] {display: none !important;}
[data-testid="stDecoration"] {display: none !important;}
#stDecoration {display: none !important;}
</style>
'''
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- SESSION STATE ---
if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "scan_metadata" not in st.session_state:
    st.session_state.scan_metadata = {"universe": "", "timeframe": ""}
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

# --- AUTHENTICATION ---
def check_password():
    try:
        password = st.secrets.get("password")
    except Exception:
        password = None
    if password:
        if st.session_state.password_correct:
            return True
        st.markdown("<h2 style='text-align: center;'>🔐 Secure Access Required</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login"):
                entered = st.text_input("Password", type="password")
                if st.form_submit_button("Login") and entered == str(password):
                    st.session_state.password_correct = True
                    st.rerun()
                elif entered:
                    st.error("❌ Incorrect password")
        return False
    return True

if not check_password():
    st.stop()

# Market status sidebar
with st.sidebar.expander("📈 Market Status", expanded=False):
    if data_loader.is_market_open():
        st.success("🟢 NSE: Open")
    else:
        st.warning("🔴 NSE: Closed")

# --- MAIN UI ---
st.title("NSE CPR Scanner 📈")
st.markdown("ATR-Normalized Central Pivot Range — Works for all price ranges")

# Sidebar Configuration
st.sidebar.header("Scan Setup")
indices_dict = data_loader.get_all_indices_dict()
universe_options = list(indices_dict.keys()) + ["Custom List"]
selected_universe = st.sidebar.selectbox("Market Universe", universe_options, index=universe_options.index("Nifty 500") if "Nifty 500" in universe_options else 0)

timeframe_options = ["1h", "15m", "5m", "1d"]
selected_timeframe = st.sidebar.selectbox("Timeframe (Interval)", timeframe_options, index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("📡 Data Source")
data_source_options = ["yflib", "yfapi"]
selected_data_source = st.sidebar.selectbox("Data Fetch Method", data_source_options, index=1)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 CPR Close Baseline")
cpr_method_options = [
    "Intraday Candle Close",
    "Official Exchange LTP (Bhavcopy)",
    "Without Correction (Standard EOD Close)"
]
selected_cpr_method = st.sidebar.selectbox("Calculation Baseline Close", cpr_method_options, index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("📅 CPR Target Session")
session_options = ["Current Session (Today's CPR)", "Next Session (Tomorrow's CPR)"]
selected_session = st.sidebar.selectbox("Projected Session Target", session_options, index=0)
target_session_val = "Next Session" if "Next" in selected_session else "Current Session"

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Filter")
filter_options = ["All Stocks", "Narrow CPR (ATR<0.50)", "Wide CPR (ATR>1.00)", "Above TC (Bullish)", "Below BC (Bearish)", "Inside CPR (Neutral)"]
signal_filter = st.sidebar.selectbox("Show", filter_options, index=0)

if "cpr_method" not in st.session_state.scan_metadata:
    st.session_state.scan_metadata["cpr_method"] = selected_cpr_method
if "target_session" not in st.session_state.scan_metadata:
    st.session_state.scan_metadata["target_session"] = target_session_val
if "data_source" not in st.session_state.scan_metadata:
    st.session_state.scan_metadata["data_source"] = selected_data_source

if (selected_universe != st.session_state.scan_metadata["universe"] or
    selected_timeframe != st.session_state.scan_metadata["timeframe"] or
    selected_cpr_method != st.session_state.scan_metadata.get("cpr_method") or
    target_session_val != st.session_state.scan_metadata.get("target_session") or
    selected_data_source != st.session_state.scan_metadata.get("data_source")):
    st.session_state.results_df = None
    st.session_state.scan_metadata["universe"] = selected_universe
    st.session_state.scan_metadata["timeframe"] = selected_timeframe
    st.session_state.scan_metadata["cpr_method"] = selected_cpr_method
    st.session_state.scan_metadata["target_session"] = target_session_val
    st.session_state.scan_metadata["data_source"] = selected_data_source

st.sidebar.markdown("---")

with st.sidebar.expander("⚙️ Cache"):
    if st.button("🗑️ Clear OHLCV Cache"):
        count = data_loader.clear_ohlcv_cache()
        st.success(f"Cleared {count} cached files")

symbols = []
if selected_universe == "Custom List":
    custom_input = st.sidebar.text_area("Symbols (comma separated)", "RELIANCE, TCS, INFY")
    if custom_input:
        symbols = [s.strip() for s in custom_input.split(",")]
else:
    with st.spinner(f"Loading {selected_universe} stocks..."):
        actual_index = indices_dict.get(selected_universe, selected_universe)
        symbols = data_loader.get_index_constituents(actual_index)
        if not symbols:
            st.warning(f"Could not load constituents for '{selected_universe}'; using Nifty 50 fallback.")
            symbols = data_loader.get_nifty50_symbols()

st.info(f"**Scanning**: {selected_universe} | **Symbols**: {len(symbols)} | **Interval**: {selected_timeframe} | **CPR target**: {selected_session}")

# --- EXECUTION ---
if st.button("🚀 Start Market Scan", use_container_width=True):
    if not symbols:
        st.error("No valid symbols found.")
    else:
        ds_map = {
            "yflib": "yfinance",
            "yfapi": "yahoo",
        }
        data_loader.set_data_source(ds_map.get(selected_data_source, "yahoo"))

        progress_bar = st.progress(0, text="Initializing scan...")

        def update_progress(completed, total):
            pct = min(completed / total, 1.0)
            progress_bar.progress(pct, text=f"Scanning {completed}/{total} stocks...")

        scan_placeholder = st.empty()
        with scan_placeholder.container():
            st.markdown("""
            <div style="text-align: center; padding: 20px;">
                <h3>🔍 Scanning NSE Stocks...</h3>
                <p style="color: #888;">Fetching OHLCV data | Computing ATR-Normalized CPR</p>
            </div>
            """, unsafe_allow_html=True)

        with st.spinner(f"Scanning {len(symbols)} stocks on {selected_timeframe} timeframe..."):
            t0 = time.time()
            results_df = scanner.scan_market(
                symbols,
                interval=selected_timeframe,
                progress_callback=update_progress,
                close_method=selected_cpr_method,
                target_session=target_session_val
            )
            elapsed = time.time() - t0

            scan_placeholder.empty()
            progress_bar.empty()

            if not results_df.empty:
                st.session_state.results_df = results_df.sort_values(
                    by='Signal Time', ascending=False,
                    key=lambda col: pd.to_datetime(col, format='%d-%m-%Y %H:%M', errors='coerce')
                )
                total_stocks = results_df['Stock Name'].nunique()
                if 'CPR_Position' in results_df.columns:
                    above = len(results_df[results_df['CPR_Position'].str.contains('ABOVE', na=False)])
                    below = len(results_df[results_df['CPR_Position'].str.contains('BELOW', na=False)])
                    inside = len(results_df[results_df['CPR_Position'].str.contains('INSIDE', na=False)])
                    st.toast(f"✅ {elapsed:.1f}s | {total_stocks} stocks | Above TC:{above} | Below BC:{below} | Inside:{inside}", icon="⚡")
                else:
                    st.toast(f"✅ {elapsed:.1f}s | {total_stocks} stocks", icon="⚡")
            else:
                st.session_state.results_df = "EMPTY"
                st.toast(f"✅ {elapsed:.1f}s | No data found", icon="ℹ️")

            # Check if fallback was triggered from log output
            fallback_triggered = False
            for log in log_lines:
                if "Bhavcopy lookup not resolved" in log or "Bhavcopy download/parse failed" in log:
                    fallback_triggered = True
                    break
            
            if fallback_triggered:
                st.toast("⚠️ Bhavcopy missing/failed. Automatically fell back to continuous Intraday Candle Close.", icon="⚠️")

        st.session_state.scan_logs = list(log_lines)
        log_lines.clear()

# --- DISPLAY BLOCK ---
if st.session_state.results_df is not None:
    if isinstance(st.session_state.results_df, str) and st.session_state.results_df == "EMPTY":
        st.warning("No matches found for the selected criteria.")
    else:
        all_results_df = st.session_state.results_df.copy()
        full_df = all_results_df.copy()

        # Apply filter — use pd.to_numeric for safe numeric comparison
        if signal_filter == "Narrow CPR (ATR<0.50)":
            ratio = pd.to_numeric(full_df['CPR_ATR_Ratio'], errors='coerce')
            full_df = full_df[ratio < 0.50]
        elif signal_filter == "Wide CPR (ATR>1.00)":
            ratio = pd.to_numeric(full_df['CPR_ATR_Ratio'], errors='coerce')
            full_df = full_df[ratio > 1.00]
        elif signal_filter == "Above TC (Bullish)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('ABOVE', na=False)]
        elif signal_filter == "Below BC (Bearish)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('BELOW', na=False)]
        elif signal_filter == "Inside CPR (Neutral)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('INSIDE', na=False)]

        # Show last date only in table — guard against all-NaT
        if 'Signal Time' in full_df.columns and not full_df['Signal Time'].isna().all():
            signal_dates = pd.to_datetime(full_df['Signal Time'], errors='coerce', dayfirst=True)
            max_ts = signal_dates.max()
            if pd.isna(max_ts):
                display_df = full_df.copy()
                last_date = None
            else:
                last_date = max_ts.date()
                display_df = full_df[signal_dates.dt.date == last_date].copy()
        else:
            display_df = full_df.copy()
            last_date = None

        if full_df.empty:
            st.warning("No stocks match your filter.")
        else:
            total_signals = len(full_df)
            display_count = len(display_df)
            if last_date:
                st.info(f"📅 Showing **{display_count}** stocks from **{last_date.strftime('%d-%b-%Y')}** | Total: **{total_signals}** rows")

            # Pagination only when rows > 4000
            PAGE_SIZE = 4000
            if len(display_df) > PAGE_SIZE:
                total_pages = (len(display_df) + PAGE_SIZE - 1) // PAGE_SIZE
                col_pg1, col_pg2, col_pg3 = st.columns([1, 1, 2])
                with col_pg1:
                    page_num = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="page_num")
                with col_pg2:
                    st.markdown(f"<div style='padding-top: 32px; color: #888;'>of {total_pages} pages</div>", unsafe_allow_html=True)
                with col_pg3:
                    pg_start = (page_num - 1) * PAGE_SIZE
                    pg_end = min(pg_start + PAGE_SIZE, len(display_df))
                    st.markdown(f"<div style='padding-top: 32px; color: #888;'>Rows {pg_start + 1}–{pg_end} of {len(display_df)}</div>", unsafe_allow_html=True)
                show_df = display_df.iloc[pg_start:pg_end]
            else:
                show_df = display_df

            def style_cpr(val):
                val_str = str(val)
                if 'EXTREME NARROW' in val_str:
                    return "background-color: #0d47a1; color: white; font-weight: bold;"
                elif 'VERY NARROW' in val_str:
                    return "background-color: #1b5e20; color: white; font-weight: bold;"
                elif 'NARROW' in val_str:
                    return "background-color: #2e7d32; color: white;"
                elif 'NORMAL' in val_str:
                    return "background-color: #1565c0; color: white;"
                elif 'SLIGHTLY WIDE' in val_str:
                    return "background-color: #e65100; color: white;"
                elif 'WIDE' in val_str:
                    return "background-color: #b71c1c; color: white;"
                elif 'VERY WIDE' in val_str:
                    return "background-color: #424242; color: #ff8a80;"
                return ""

            def style_position(val):
                val_str = str(val)
                if 'ABOVE' in val_str:
                    return "background-color: #1b5e20; color: white; font-weight: bold;"
                elif 'BELOW' in val_str:
                    return "background-color: #b71c1c; color: white; font-weight: bold;"
                elif 'INSIDE' in val_str:
                    return "background-color: #e65100; color: white;"
                return ""

            display_cols = ['Stock Name', 'Open', 'High', 'Low', 'Close', 'CPR_Position', 'Signal Time', 'Volume',
                           'Prev_Open', 'Prev_High', 'Prev_Low', 'Prev_Close', 'Prev_Volume',
                           'CPR_PP', 'CPR_BC', 'CPR_TC', 'CPR_Width', 'CPR_ATR', 'CPR_ATR_Ratio', 'CPR_Type',
                           'CPR_R1', 'CPR_R2', 'CPR_R3', 'CPR_S1', 'CPR_S2', 'CPR_S3']
            display_cols = [c for c in display_cols if c in show_df.columns]
            other_cols = [c for c in show_df.columns if c not in display_cols]
            ordered_cols = display_cols + other_cols

            styled_df = show_df[ordered_cols].style.map(style_cpr, subset=["CPR_Type"])
            if 'CPR_Position' in show_df.columns:
                styled_df = styled_df.map(style_position, subset=["CPR_Position"])

            st.dataframe(
                styled_df,
                column_config={
                    "Stock Name": "Symbol",
                    "Open": st.column_config.NumberColumn("Open", format="₹ %.2f"),
                    "High": st.column_config.NumberColumn("High", format="₹ %.2f"),
                    "Low": st.column_config.NumberColumn("Low", format="₹ %.2f"),
                    "Close": st.column_config.NumberColumn("LTP (Close)", format="₹ %.2f", help="Last Traded Price = Close of the candle"),
                    "CPR_Position": st.column_config.TextColumn("LTP vs CPR", help="ABOVE TC = Bullish | BELOW BC = Bearish | INSIDE CPR = Neutral/Range-bound"),
                    "Signal Time": "Time (IST)",
                    "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                    "Prev_Open": st.column_config.NumberColumn("Prev O", format="%.2f", help="Previous Day Open"),
                    "Prev_High": st.column_config.NumberColumn("Prev H", format="%.2f", help="Previous Day High"),
                    "Prev_Low": st.column_config.NumberColumn("Prev L", format="%.2f", help="Previous Day Low"),
                    "Prev_Close": st.column_config.NumberColumn("Prev C", format="%.2f", help="Previous Day Close"),
                    "Prev_Volume": st.column_config.NumberColumn("Prev Vol", format="%d", help="Previous Day Volume (1d timeframe)"),
                    "CPR_PP": st.column_config.NumberColumn("CPR PP", format="%.2f", help="Central Pivot Point"),
                    "CPR_BC": st.column_config.NumberColumn("CPR BC", format="%.2f", help="Bottom Central of CPR"),
                    "CPR_TC": st.column_config.NumberColumn("CPR TC", format="%.2f", help="Top Central of CPR"),
                    "CPR_Width": st.column_config.NumberColumn("CPR Width", format="%.2f", help="CPR Width in points (TC - BC)"),
                    "CPR_ATR": st.column_config.NumberColumn("ATR(14)", format="%.2f", help="Average True Range (14 periods)"),
                    "CPR_ATR_Ratio": st.column_config.NumberColumn("ATR Ratio", format="%.3f", help="CPR Width / ATR(14). <0.30=Narrow, 0.30-1.00=Normal, >1.00=Wide"),
                    "CPR_Type": st.column_config.TextColumn("CPR Type", help="ATR-Normalized classification"),
                    "CPR_R1": st.column_config.NumberColumn("R1", format="%.2f", help="Resistance 1 = 2*PP - Low"),
                    "CPR_R2": st.column_config.NumberColumn("R2", format="%.2f", help="Resistance 2 = PP + (High - Low)"),
                    "CPR_R3": st.column_config.NumberColumn("R3", format="%.2f", help="Resistance 3 = H + 2*(PP - Low)"),
                    "CPR_S1": st.column_config.NumberColumn("S1", format="%.2f", help="Support 1 = 2*PP - High"),
                    "CPR_S2": st.column_config.NumberColumn("S2", format="%.2f", help="Support 2 = PP - (High - Low)"),
                    "CPR_S3": st.column_config.NumberColumn("S3", format="%.2f", help="Support 3 = L - 2*(H - PP)"),
                },
                hide_index=True,
                use_container_width=True
            )

            # Download button
            csv = full_df.to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 Download Full Data ({len(full_df)} rows)", csv, "cpr_scan_full.csv", "text/csv", use_container_width=True)

# --- COLUMN DESCRIPTIONS ---
st.markdown("---")
st.markdown("### 📊 Signal Table — Column Descriptions & Formulas")

st.markdown("""
All CPR levels are calculated from the **previous trading day's daily OHLC** (1d timeframe) using the **Zerodha rounding method**.
OHLCV columns (Open, High, Low, Close, Volume) reflect the **last candle** of the selected timeframe (e.g., 1h, 15m, 5m).
""")

with st.expander("💰 Price Columns — Open, High, Low, Close (LTP)", expanded=False):
    st.markdown("""
    These columns show OHLC of the **last candle** in the selected timeframe (1h/15m/5m/1d).

    | Column | Description | Source |
    |--------|-------------|--------|
    | **Open** | Opening price of the last candle | Selected timeframe (e.g., 1h candle at 14:15) |
    | **High** | Highest price reached in the last candle | Selected timeframe |
    | **Low** | Lowest price reached in the last candle | Selected timeframe |
    | **Close (LTP)** | Closing price = Last Traded Price | Selected timeframe |

    > **Note:** For 1h timeframe, these values come from the 14:15 candle. They are **NOT** daily OHLC.
    """)

with st.expander("📊 Volume", expanded=False):
    st.markdown("""
    | Column | Description | Source |
    |--------|-------------|--------|
    | **Volume** | Traded volume in the last candle | Selected timeframe (e.g., 1h candle) |

    > **Note:** This is the volume of a single candle, not the full day. For daily volume, see Prev Volume.
    """)

with st.expander("🎯 LTP vs CPR Position", expanded=False):
    st.markdown("""
    Compares the **Close (LTP)** of the last candle against **CPR TC** and **CPR BC** levels.

    | Position | Condition | Meaning |
    |----------|-----------|---------|
    | **ABOVE TC (Bullish)** | Close > TC | Price is above the CPR range — bullish bias |
    | **BELOW BC (Bearish)** | Close < BC | Price is below the CPR range — bearish bias |
    | **INSIDE CPR (Neutral)** | BC ≤ Close ≤ TC | Price is within the CPR range — range-bound / wait |

    **Formula:**
    ```
    if Close > TC  → ABOVE TC (Bullish)
    if Close < BC  → BELOW BC (Bearish)
    else           → INSIDE CPR (Neutral)
    ```
    """)

with st.expander("🕐 Signal Time", expanded=False):
    st.markdown("""
    | Column | Description |
    |--------|-------------|
    | **Signal Time** | Timestamp of the **last candle** in the selected timeframe (IST) |

    For 1h timeframe, this is typically 14:15 IST (last hourly candle of the trading day).
    """)

with st.expander("📅 Previous Day OHLCV (1d Timeframe)", expanded=False):
    st.markdown("""
    These values are fetched from the **daily (1d) timeframe** — they represent the **complete previous trading day**.
    Used for CPR calculation. Always from 1d data regardless of the selected timeframe.

    | Column | Description | Formula |
    |--------|-------------|---------|
    | **Prev Open** | Previous day's opening price | Daily candle Open |
    | **Prev High** | Previous day's highest price | Daily candle High |
    | **Prev Low** | Previous day's lowest price | Daily candle Low |
    | **Prev Close** | Previous day's closing price | Daily candle Close |
    | **Prev Volume** | Previous day's total traded volume | Daily candle Volume |

    > **Important:** These are **daily** values, not from the selected timeframe. They match what Zerodha/Kite shows for the previous day.
    """)

with st.expander("📐 CPR Levels — PP, BC, TC, Width", expanded=False):
    st.markdown("""
    Calculated from **previous day's High (H), Low (L), Close (C)** using Zerodha rounding method.

    | Column | Name | Formula | Rounding |
    |--------|------|---------|----------|
    | **CPR PP** | Central Pivot Point | (H + L + C) / 3 | Round to 1 decimal |
    | **CPR BC** | Bottom Central | (H + L) / 2 | Round to 2 decimals |
    | **CPR TC** | Top Central | 2 × PP − BC | Round to 2 decimals |
    | **CPR Width** | Range Width | abs(TC − BC) | 2 decimals |

    **Zerodha Method:** PP is rounded to **1 decimal first**, then TC is computed from the rounded PP. This matches Zerodha/Kite/ChartIQ exactly.

    **Example (RVNL):**
    ```
    Prev Day: H=278.30, L=270.35, C=271.55
    PP = round((278.30 + 270.35 + 271.55) / 3, 1) = 273.4
    BC = round((278.30 + 270.35) / 2, 2) = 274.32
    TC = round(2 × 273.4 − 274.32, 2) = 272.48
    Width = abs(272.48 − 274.32) = 1.84
    ```
    """)

with st.expander("📈 ATR(14) & CPR Classification", expanded=False):
    st.markdown("""
    **ATR(14)** is calculated from the **daily (1d) timeframe** — Average True Range over 14 periods.
    **ATR Ratio** = CPR Width / ATR(14) — normalizes CPR width across all price ranges.

    | Column | Description | Formula |
    |--------|-------------|---------|
    | **CPR ATR** | Daily ATR(14) value | ATR of previous day (1d timeframe) |
    | **CPR ATR Ratio** | Width / ATR(14) | Normalized width — comparable across stocks |
    | **CPR Type** | Classification | Based on ATR Ratio thresholds |

    **ATR Ratio Classification:**

    | ATR Ratio | Classification | Trading Implication |
    |-----------|----------------|---------------------|
    | < 0.15 | EXTREME NARROW | Major breakout expected — highest probability setup |
    | 0.15 - 0.30 | VERY NARROW | Strong breakout expected |
    | 0.30 - 0.50 | NARROW | Good breakout setup |
    | 0.50 - 1.00 | NORMAL | Follow the trend |
    | 1.00 - 1.50 | SLIGHTLY WIDE | Cautious — may consolidate |
    | 1.50 - 2.00 | WIDE | Range-bound trading |
    | > 2.00 | VERY WIDE | Avoid — no clear edge |

    **Why ATR-Normalized?** A ₹10 width means different things for a ₹100 stock vs a ₹10,000 stock.
    ATR Ratio makes it universal — 0.20 means the same tight squeeze regardless of price.
    """)

with st.expander("🔴🟢 Support & Resistance Levels — R1, R2, R3, S1, S2, S3", expanded=False):
    st.markdown("""
    Standard pivot-based Support and Resistance levels, computed from **previous day's H, L, C** using the rounded PP.

    | Level | Formula | Description |
    |-------|---------|-------------|
    | **R1** | 2 × PP − L | First resistance — breakout target |
    | **R2** | PP + (H − L) | Second resistance — strong target |
    | **R3** | H + 2 × (PP − L) | Third resistance — extended target |
    | **S1** | 2 × PP − H | First support — pullback target |
    | **S2** | PP − (H − L) | Second support — strong support |
    | **S3** | L − 2 × (H − PP) | Third support — extended support |

    **Trading Use:**
    - Price above **R1** → strong bullish momentum, target **R2**
    - Price below **S1** → strong bearish momentum, target **S2**
    - Price between **S1 and R1** → range-bound within normal pivot levels
    """)

st.markdown("---")

# --- SCAN LOGS ---
st.markdown("---")
st.markdown("### 📋 Scan Logs")
if "scan_logs" in st.session_state and st.session_state.scan_logs:
    with st.expander("Show scan logs", expanded=False):
        for line in st.session_state.scan_logs[-100:]:
            if "[ERROR]" in line:
                st.error(line)
            elif "[WARNING]" in line:
                st.warning(line)
            elif "[INFO]" in line:
                st.info(line)
            else:
                st.text(line)
else:
    st.caption("Logs will appear here after a scan completes.")
