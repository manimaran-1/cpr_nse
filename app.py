import streamlit as st
import pandas as pd
import scanner
import data_loader
import config
import reporter
import pytz
import os
import requests
import io
import logging
from datetime import datetime, date, timedelta

# --- LOG CAPTURE FOR UI ---
log_lines = []

class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_lines.append(msg)

# Attach handler to all relevant loggers
log_handler = StreamlitLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
log_handler.setLevel(logging.INFO)
for name in ['scanner', 'data_loader']:
    lg = logging.getLogger(name)
    lg.addHandler(log_handler)

# --- UI CONFIGURATION ---
st.set_page_config(page_title="NSE Stock Scanner 2.0", layout="wide", page_icon="📈")

# Security and CSS
hide_st_style = '''
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display: none !important;}
</style>
'''
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "scan_metadata" not in st.session_state:
    st.session_state.scan_metadata = {"universe": "", "timeframe": ""}
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

# --- SECURE CREDENTIALS ---
BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)

def validate_credentials():
    if not BOT_TOKEN or not CHAT_ID:
        st.error("🚨 **Critical Error**: Telegram Bot Token or Chat ID not found.")
        st.info("Please set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your environment or Streamlit Secrets.")
        st.stop()

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

validate_credentials()

# Market status sidebar
with st.sidebar.expander("📈 Market Status", expanded=False):
    if data_loader.is_market_open():
        st.success("🟢 NSE: Open")
    else:
        st.warning("🔴 NSE: Closed")

def send_to_telegram(df, universe, timeframe):
    report_parts = reporter.generate_report(df, universe, timeframe)
    if not report_parts:
        return False

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    doc_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {'document': ('nse2_scan_results.csv', csv_buffer.getvalue())}
    data = {'chat_id': CHAT_ID, 'caption': report_parts[0], 'parse_mode': 'Markdown'}

    try:
        response = requests.post(doc_url, files=files, data=data, timeout=20)
        if response.status_code != 200:
            st.error(f"Telegram Error (Doc): {response.text}")
            return False

        msg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for part in report_parts[1:]:
            msg_data = {'chat_id': CHAT_ID, 'text': part, 'parse_mode': 'Markdown'}
            requests.post(msg_url, json=msg_data, timeout=15)

        return True
    except Exception as e:
        st.error(f"Failed to send to Telegram: {e}")
    return False

# --- MAIN UI ---
st.title("NSE Stock Scanner 📈 v2.0")
st.markdown("CPR + Pine Signal Scanner (EMA, Stoch RSI, SMI, MACD)")

# Sidebar Configuration
st.sidebar.header("Scan Setup")
indices_dict = data_loader.get_all_indices_dict()
universe_options = list(indices_dict.keys()) + ["Custom List"]
selected_universe = st.sidebar.selectbox("Market Universe", universe_options, index=universe_options.index("Nifty 500") if "Nifty 500" in universe_options else 0)

timeframe_options = ["1h", "15m", "5m", "1d"]
selected_timeframe = st.sidebar.selectbox("Timeframe (Interval)", timeframe_options, index=0)

# Data source selector
st.sidebar.markdown("---")
st.sidebar.subheader("📡 Data Source")
data_source_options = [
    "Yahoo Finance Direct API",
    "yfinance Library",
]
selected_data_source = st.sidebar.selectbox("Data Fetch Method", data_source_options, index=0)

st.sidebar.markdown("---")

# --- DISPLAY FILTER ---
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Signal Filter")
filter_options = ["All Signals", "Pine BUY Only", "Narrow CPR (ATR<0.50)", "Wide CPR (ATR>1.00)"]
signal_filter = st.sidebar.selectbox("Show signals", filter_options, index=0)

# Reset Results if Universe or Timeframe changes
if (selected_universe != st.session_state.scan_metadata["universe"] or
    selected_timeframe != st.session_state.scan_metadata["timeframe"]):
    st.session_state.results_df = None
    st.session_state.scan_metadata["universe"] = selected_universe
    st.session_state.scan_metadata["timeframe"] = selected_timeframe

st.sidebar.markdown("---")

# Strategy Threshold Display
with st.sidebar.expander("📊 Active Strategy Logic"):
    strat = config.STRATEGY_CONFIG
    st.write(f"**EMA Layers**: {', '.join(map(str, strat['EMA']))}")
    st.write(f"**Stoch RSI K Min**: {strat['STOCH_RSI_K_MIN']}")
    st.write(f"**SMI Min**: {strat['SMI_MIN']}")
    st.write(f"**MACD Min**: {strat['MACD_MIN']}")

# Cache Management
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
        # Set data source before scanning
        ds_map = {
            "Yahoo Finance Direct API": "yahoo",
            "yfinance Library": "yfinance",
        }
        data_loader.set_data_source(ds_map.get(selected_data_source, "yahoo"))

        # Scanning animation
        progress_bar = st.progress(0, text="Initializing scan...")
        status_text = st.empty()

        def update_progress(completed, total):
            pct = min(completed / total, 1.0)
            progress_bar.progress(pct, text=f"Scanning {completed}/{total} stocks...")

        scan_placeholder = st.empty()
        with scan_placeholder.container():
            st.markdown("""
            <div style="text-align: center; padding: 20px;">
                <h3>🔍 Scanning NSE Stocks...</h3>
                <p style="color: #888;">Fetching OHLCV data | Computing CPR + Pine Signal indicators</p>
            </div>
            """, unsafe_allow_html=True)

        with st.spinner(f"Scanning {len(symbols)} stocks on {selected_timeframe} timeframe..."):
            import time
            t0 = time.time()
            results_df = scanner.scan_market(
                symbols,
                interval=selected_timeframe,
                progress_callback=update_progress
            )
            elapsed = time.time() - t0

            scan_placeholder.empty()
            progress_bar.empty()
            status_text.empty()

            if not results_df.empty:
                st.session_state.results_df = results_df.sort_values(by='Signal Time', ascending=False)
                total_stocks = results_df['Stock Name'].nunique()
                pine_count = len(results_df[results_df['Pine Signal'] == 'BUY'])
                narrow_count = len(results_df[results_df['CPR_Type'].str.contains('NARROW', na=False)])
                wide_count = len(results_df[results_df['CPR_Type'].str.contains('WIDE', na=False)])
                st.toast(f"✅ Scan completed in {elapsed:.1f}s | {total_stocks} stocks | Pine BUY:{pine_count} | Narrow:{narrow_count} Wide:{wide_count}", icon="⚡")
            else:
                st.session_state.results_df = "EMPTY"
                st.toast(f"✅ Scan completed in {elapsed:.1f}s | No data found", icon="ℹ️")

        st.session_state.scan_logs = list(log_lines)
        log_lines.clear()

# --- PERSISTENT DISPLAY BLOCK ---
if st.session_state.results_df is not None:
    if isinstance(st.session_state.results_df, str) and st.session_state.results_df == "EMPTY":
        st.warning("No matches found for the selected criteria.")
    else:
        all_results_df = st.session_state.results_df.copy()

        # === FILTER FULL DATA (for download) ===
        full_df = all_results_df.copy()

        if signal_filter == "Pine BUY Only":
            full_df = full_df[full_df['Pine Signal'] == 'BUY']
        elif signal_filter == "Narrow CPR (ATR<0.50)":
            full_df = full_df[full_df['CPR_ATR_Ratio'].apply(lambda x: float(x) < 0.50 if x != '' else False)]
        elif signal_filter == "Wide CPR (ATR>1.00)":
            full_df = full_df[full_df['CPR_ATR_Ratio'].apply(lambda x: float(x) > 1.00 if x != '' else False)]

        # === SHOW ONLY LAST DATE DATA IN TABLE ===
        if 'Signal Time' in full_df.columns and not full_df['Signal Time'].isna().all():
            signal_dates = pd.to_datetime(full_df['Signal Time'], errors='coerce', dayfirst=True)
            last_date = signal_dates.max().date()
            display_df = full_df[signal_dates.dt.date == last_date].copy()
        else:
            display_df = full_df.copy()
            last_date = None

        if full_df.empty:
            st.warning("No signals match your filter.")
        else:
            # Summary metrics
            total_signals = len(full_df)
            display_count = len(display_df)
            if last_date:
                st.info(f"📅 Showing **{display_count}** signals from **{last_date.strftime('%d-%b-%Y')}** (latest date) | Total data: **{total_signals}** rows across all dates")

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

            def style_pine(val):
                if val == 'BUY':
                    return "background-color: #1b5e20; color: white; font-weight: bold;"
                return ""

            # Table shows last date only; download has all data
            display_cols = ['Stock Name', 'LTP', 'Pine Signal', 'Signal Time',
                           'CPR_PP', 'CPR_BC', 'CPR_TC', 'CPR_Width', 'CPR_ATR', 'CPR_ATR_Ratio', 'CPR_Type',
                           'RSI', 'Stoch RSI K', 'SMI', 'MACD', 'MACD_Hist']
            display_cols = [c for c in display_cols if c in display_df.columns]
            other_cols = [c for c in display_df.columns if c not in display_cols]
            ordered_cols = display_cols + other_cols

            styled_df = display_df[ordered_cols].style.map(style_cpr, subset=["CPR_Type"]).map(style_pine, subset=["Pine Signal"])

            st.dataframe(
                styled_df,
                column_config={
                    "Stock Name": "Symbol",
                    "LTP": st.column_config.NumberColumn("LTP", format="₹ %.2f"),
                    "Pine Signal": st.column_config.TextColumn("Pine Signal", help="BUY when EMA>5/9/21, StochRSI K>70, SMI>30, MACD>0.75"),
                    "Signal Time": "Time (IST)",
                    "CPR_PP": st.column_config.NumberColumn("CPR PP", format="%.2f", help="Central Pivot Point"),
                    "CPR_BC": st.column_config.NumberColumn("CPR BC", format="%.2f", help="Bottom Central of CPR"),
                    "CPR_TC": st.column_config.NumberColumn("CPR TC", format="%.2f", help="Top Central of CPR"),
                    "CPR_Width": st.column_config.NumberColumn("CPR Width", format="%.2f", help="CPR Width in points (TC - BC)"),
                    "CPR_ATR": st.column_config.NumberColumn("ATR(14)", format="%.2f", help="Average True Range (14 periods)"),
                    "CPR_ATR_Ratio": st.column_config.NumberColumn("ATR Ratio", format="%.3f", help="CPR Width / ATR(14). Universal metric: <0.30=Narrow, 0.30-1.00=Normal, >1.00=Wide"),
                    "CPR_Type": st.column_config.TextColumn("CPR Type", help="ATR-Normalized: EXTREME NARROW(<0.15) | VERY NARROW(0.15-0.30) | NARROW(0.30-0.50) | NORMAL(0.50-1.00) | SLIGHTLY WIDE(1.00-1.50) | WIDE(1.50-2.00) | VERY WIDE(>2.00)"),
                    "RSI": st.column_config.NumberColumn("RSI", format="%.1f"),
                    "Stoch RSI K": st.column_config.NumberColumn("Stoch RSI K", format="%.1f"),
                    "SMI": st.column_config.NumberColumn("SMI", format="%.2f"),
                    "MACD": st.column_config.NumberColumn("MACD", format="%.2f"),
                    "MACD_Hist": st.column_config.NumberColumn("MACD Hist", format="%.2f"),
                },
                hide_index=True,
                width="stretch"
            )

            # Download = ALL data, Telegram = ALL data
            col1, col2 = st.columns(2)
            with col1:
                csv = full_df.to_csv(index=False).encode('utf-8')
                st.download_button(f"📥 Download Full Data ({len(full_df)} rows)", csv, "cpr_scan_full.csv", "text/csv", width="stretch")
            with col2:
                if st.button("📤 Send to Telegram", width="stretch"):
                    if send_to_telegram(full_df, selected_universe, selected_timeframe):
                        st.success("✅ Results sent to Telegram!")
                    else:
                        st.error("❌ Failed to send to Telegram")

# --- CPR DESCRIPTION ---
st.markdown("---")
st.markdown("### 📊 Central Pivot Range (CPR) — ATR-Normalized Width")

col_cpr1, col_cpr2 = st.columns([2, 1])

with col_cpr1:
    st.markdown("""
    **CPR** is a key support/resistance indicator calculated from the **previous day's High, Low, and Close**.

    | Level | Formula | Description |
    |-------|---------|-------------|
    | **PP** (Pivot Point) | (H + L + C) / 3 | Central anchor — average price of previous session |
    | **BC** (Bottom Central) | (H + L) / 2 | Midpoint of previous day's range |
    | **TC** (Top Central) | 2 × PP − BC | Mirror of BC above the pivot |
    | **Width** | abs(TC − BC) | Distance between TC and BC (in points) |
    | **ATR Ratio** | Width / ATR(14) | **Universal metric** — works for all price ranges |

    **ATR-Normalized Classification (Universal):**

    | ATR Ratio | Classification | Trading Action |
    |-----------|----------------|----------------|
    | < 0.15 | 🔥🔥🔥 EXTREME NARROW | Major breakout expected |
    | 0.15 - 0.30 | 🔥🔥 VERY NARROW | Strong breakout setup |
    | 0.30 - 0.50 | ⚡ NARROW | Good breakout candidate |
    | 0.50 - 1.00 | 📊 NORMAL | Trend following |
    | 1.00 - 1.50 | 📈 SLIGHTLY WIDE | Cautious trend |
    | 1.50 - 2.00 | 📉 WIDE | Range trading |
    | > 2.00 | 💤 VERY WIDE | Avoid / consolidation |

    **Why ATR-Normalized?**
    - Works equally for ₹10 stocks and ₹10,000 stocks
    - Accounts for each stock's natural volatility
    - Industry-standard professional method
    """)

with col_cpr2:
    st.info("""
    **How to use CPR:**

    1. **ATR Ratio < 0.30** → Look for breakout signals (Pine BUY)
    2. **ATR Ratio 0.30-1.00** → Normal trading, trend follow
    3. **ATR Ratio > 1.00** → Range-bound, wait for breakout
    4. Price **above TC** → Bullish bias
    5. Price **below BC** → Bearish bias
    6. Price **between BC and TC** → Wait for breakout
    """)

# --- SCAN LOGS DISPLAY ---
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
