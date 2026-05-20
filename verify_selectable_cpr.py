import sys
import os
import pandas as pd
from datetime import datetime, date

# Add the project path to sys.path
project_path = r"C:\Users\Admin\Downloads\nse2_automation_fyersoffapiimplement\cpr_2"
sys.path.append(project_path)

import data_loader
import indicators
import scanner

print("=== STARTING DUAL-SESSION CPR VERIFICATION ===")

symbol = "NSE:RELIANCE-EQ"
print(f"Testing with symbol: {symbol}")

# Fetch data
print("Fetching daily OHLC data...")
daily_df = data_loader.fetch_data(symbol, interval='1d')
if daily_df.empty:
    print("Error: Could not fetch daily OHLC data.")
    sys.exit(1)

print("Fetching 1h intraday data...")
intraday_df = data_loader.fetch_data(symbol, interval='1h')
if intraday_df.empty:
    print("Error: Could not fetch intraday 1h data.")
    sys.exit(1)

# Align dates
unique_dates = sorted(list(set(intraday_df.index.date)))
if len(unique_dates) < 2:
    print("Error: Insufficient dates.")
    sys.exit(1)

print(f"Dataset unique dates: {unique_dates[-3:]}")

# 1. Calculate Today's CPR (Current Session)
print("\n--- TEST A: Current Session (Today's CPR) ---")
cpr_today = indicators.calculate_cpr(
    intraday_df,
    daily_df=daily_df,
    symbol=symbol,
    close_method="Intraday Candle Close",
    target_session="Current Session"
)
print("CPR PP (Today):", cpr_today['CPR_PP'].iloc[-1])
print("CPR TC (Today):", cpr_today['CPR_TC'].iloc[-1])
print("CPR BC (Today):", cpr_today['CPR_BC'].iloc[-1])
print("Baseline Close (Yesterday's 15:30):", cpr_today['Prev_Close'].iloc[-1])

# 2. Calculate Tomorrow's CPR (Next Session)
print("\n--- TEST B: Next Session (Tomorrow's CPR) ---")
cpr_tomorrow = indicators.calculate_cpr(
    intraday_df,
    daily_df=daily_df,
    symbol=symbol,
    close_method="Intraday Candle Close",
    target_session="Next Session"
)
print("CPR PP (Tomorrow):", cpr_tomorrow['CPR_PP'].iloc[-1])
print("CPR TC (Tomorrow):", cpr_tomorrow['CPR_TC'].iloc[-1])
print("CPR BC (Tomorrow):", cpr_tomorrow['CPR_BC'].iloc[-1])
print("Baseline Close (Today's 15:30):", cpr_tomorrow['Prev_Close'].iloc[-1])

# Let's perform a manual check of the tomorrow's CPR formula:
latest_daily = daily_df.iloc[-1]
latest_daily_date = daily_df.index[-1].date()
print(f"\nManual check baseline (Today's date: {latest_daily_date}):")
print(f"Today's Daily High: {latest_daily['high']}")
print(f"Today's Daily Low: {latest_daily['low']}")
today_intraday_close = intraday_df[intraday_df.index.date == latest_daily_date]['close'].iloc[-1]
print(f"Today's Intraday Close: {today_intraday_close}")

manual_pp_raw = (latest_daily['high'] + latest_daily['low'] + today_intraday_close) / 3
manual_bc_raw = (latest_daily['high'] + latest_daily['low']) / 2
manual_tc_raw = 2 * manual_pp_raw - manual_bc_raw
if manual_tc_raw < manual_bc_raw:
    manual_tc_raw, manual_bc_raw = manual_bc_raw, manual_tc_raw

print(f"\nCalculated manual Tomorrow's CPR:")
print(f"PP: {round(manual_pp_raw, 2)}")
print(f"TC: {round(manual_tc_raw, 2)}")
print(f"BC: {round(manual_bc_raw, 2)}")

print("\n--- DUAL SESSION VALIDATION ---")
success = (
    cpr_tomorrow['CPR_PP'].iloc[-1] == round(manual_pp_raw, 2) and
    cpr_tomorrow['CPR_TC'].iloc[-1] == round(manual_tc_raw, 2) and
    cpr_tomorrow['CPR_BC'].iloc[-1] == round(manual_bc_raw, 2)
)
if success:
    print("SUCCESS: Tomorrow's CPR correctly uses Today's completed OHLC as its baseline!")
else:
    print("FAILURE: Tomorrow's CPR calculations do not match today's OHLC baseline.")

print("\n=== VERIFICATION RUN COMPLETE ===")
