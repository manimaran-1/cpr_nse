import streamlit as st
import pandas as pd
import scanner
import data_loader
import pytz
import logging
from datetime import datetime

# --- LOG CAPTURE FOR UI ---
log_lines = []

class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_lines.append(msg)

log_handler = StreamlitLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
log_handler.setLevel(logging.INFO)
for name in ['scanner', 'data_loader']:
    lg = logging.getLogger(name)
    lg.addHandler(log_handler)

# --- UI CONFIGURATION ---
st.set_page_config(page_title="NSE CPR Scanner", layout="wide", page_icon="📈")

hide_st_style = '''
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display: none !important;}
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
    password = st.secrets.get("password")
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
data_source_options = ["Yahoo Finance Direct API", "yfinance Library"]
selected_data_source = st.sidebar.selectbox("Data Fetch Method", data_source_options, index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Filter")
filter_options = ["All Stocks", "Narrow CPR (ATR<0.50)", "Wide CPR (ATR>1.00)", "Above TC (Bullish)", "Below BC (Bearish)", "Inside CPR (Neutral)"]
signal_filter = st.sidebar.selectbox("Show", filter_options, index=0)

if (selected_universe != st.session_state.scan_metadata["universe"] or
    selected_timeframe != st.session_state.scan_metadata["timeframe"]):
    st.session_state.results_df = None
    st.session_state.scan_metadata["universe"] = selected_universe
    st.session_state.scan_metadata["timeframe"] = selected_timeframe

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

st.info(f"**Scanning**: {selected_universe} | **Symbols**: {len(symbols)} | **Interval**: {selected_timeframe}")

# --- EXECUTION ---
if st.button("🚀 Start Market Scan", width="stretch"):
    if not symbols:
        st.error("No valid symbols found.")
    else:
        ds_map = {
            "Yahoo Finance Direct API": "yahoo",
            "yfinance Library": "yfinance",
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
            import time
            t0 = time.time()
            results_df = scanner.scan_market(symbols, interval=selected_timeframe, progress_callback=update_progress)
            elapsed = time.time() - t0

            scan_placeholder.empty()
            progress_bar.empty()

            if not results_df.empty:
                st.session_state.results_df = results_df.sort_values(by='Signal Time', ascending=False)
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

        st.session_state.scan_logs = list(log_lines)
        log_lines.clear()

# --- DISPLAY BLOCK ---
if st.session_state.results_df is not None:
    if isinstance(st.session_state.results_df, str) and st.session_state.results_df == "EMPTY":
        st.warning("No matches found for the selected criteria.")
    else:
        all_results_df = st.session_state.results_df.copy()
        full_df = all_results_df.copy()

        # Apply filter
        if signal_filter == "Narrow CPR (ATR<0.50)":
            full_df = full_df[full_df['CPR_ATR_Ratio'].apply(lambda x: float(x) < 0.50 if x != '' else False)]
        elif signal_filter == "Wide CPR (ATR>1.00)":
            full_df = full_df[full_df['CPR_ATR_Ratio'].apply(lambda x: float(x) > 1.00 if x != '' else False)]
        elif signal_filter == "Above TC (Bullish)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('ABOVE', na=False)]
        elif signal_filter == "Below BC (Bearish)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('BELOW', na=False)]
        elif signal_filter == "Inside CPR (Neutral)" and 'CPR_Position' in full_df.columns:
            full_df = full_df[full_df['CPR_Position'].str.contains('INSIDE', na=False)]

        # Show last date only in table
        if 'Signal Time' in full_df.columns and not full_df['Signal Time'].isna().all():
            signal_dates = pd.to_datetime(full_df['Signal Time'], errors='coerce', dayfirst=True)
            last_date = signal_dates.max().date()
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
                           'CPR_PP', 'CPR_BC', 'CPR_TC', 'CPR_Width', 'CPR_ATR', 'CPR_ATR_Ratio', 'CPR_Type']
            display_cols = [c for c in display_cols if c in display_df.columns]
            other_cols = [c for c in display_df.columns if c not in display_cols]
            ordered_cols = display_cols + other_cols

            styled_df = display_df[ordered_cols].style.map(style_cpr, subset=["CPR_Type"])
            if 'CPR_Position' in display_df.columns:
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
                    "CPR_PP": st.column_config.NumberColumn("CPR PP", format="%.2f", help="Central Pivot Point"),
                    "CPR_BC": st.column_config.NumberColumn("CPR BC", format="%.2f", help="Bottom Central of CPR"),
                    "CPR_TC": st.column_config.NumberColumn("CPR TC", format="%.2f", help="Top Central of CPR"),
                    "CPR_Width": st.column_config.NumberColumn("CPR Width", format="%.2f", help="CPR Width in points (TC - BC)"),
                    "CPR_ATR": st.column_config.NumberColumn("ATR(14)", format="%.2f", help="Average True Range (14 periods)"),
                    "CPR_ATR_Ratio": st.column_config.NumberColumn("ATR Ratio", format="%.3f", help="CPR Width / ATR(14). <0.30=Narrow, 0.30-1.00=Normal, >1.00=Wide"),
                    "CPR_Type": st.column_config.TextColumn("CPR Type", help="ATR-Normalized classification"),
                },
                hide_index=True,
                width="stretch"
            )

            # Download button
            csv = full_df.to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 Download Full Data ({len(full_df)} rows)", csv, "cpr_scan_full.csv", "text/csv", width="stretch")

# --- CPR DESCRIPTION ---
st.markdown("---")
st.markdown("### 📊 Central Pivot Range (CPR) — ATR-Normalized Width")

col_cpr1, col_cpr2 = st.columns([2, 1])

with col_cpr1:
    st.markdown("""
    **CPR** is calculated from the **previous day's High, Low, and Close**.

    | Level | Formula | Description |
    |-------|---------|-------------|
    | **PP** | (H + L + C) / 3 | Central anchor |
    | **BC** | (H + L) / 2 | Bottom Central |
    | **TC** | 2 × PP − BC | Top Central |
    | **Width** | abs(TC − BC) | CPR width in points |
    | **ATR Ratio** | Width / ATR(14) | Universal metric |

    **LTP vs CPR Position:**
    - **ABOVE TC** → Bullish bias, look for long setups
    - **BELOW BC** → Bearish bias, look for short setups
    - **INSIDE CPR** → Range-bound, wait for breakout

    **ATR-Normalized Classification:**

    | ATR Ratio | Classification | Action |
    |-----------|----------------|--------|
    | < 0.15 | EXTREME NARROW | Major breakout |
    | 0.15 - 0.30 | VERY NARROW | Strong breakout |
    | 0.30 - 0.50 | NARROW | Good breakout |
    | 0.50 - 1.00 | NORMAL | Trend follow |
    | 1.00 - 1.50 | SLIGHTLY WIDE | Cautious |
    | 1.50 - 2.00 | WIDE | Range trade |
    | > 2.00 | VERY WIDE | Avoid |
    """)

with col_cpr2:
    st.info("""
    **CPR Position Guide:**

    1. Price **above TC** → Bullish
    2. Price **below BC** → Bearish
    3. Price **inside CPR** → Wait

    **ATR Ratio Guide:**

    1. **< 0.30** → Breakout trading
    2. **0.30-1.00** → Trend following
    3. **> 1.00** → Range-bound
    """)

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
