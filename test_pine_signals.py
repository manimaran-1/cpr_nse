
import sys
import os
import pandas as pd
from datetime import datetime

# Add the project directory to sys.path
sys.path.append(os.getcwd())

import data_loader
import scanner
import config

def test_scan():
    # Test with Nifty Bank (12 stocks + index = 13 or 14)
    symbols = ['NSE:HDFCBANK-EQ', 'NSE:ICICIBANK-EQ', 'NSE:SBIN-EQ', 'NSE:KOTAKBANK-EQ', 'NSE:AXISBANK-EQ']
    print(f"Scanning {len(symbols)} stocks on 1h timeframe...")
    
    results_df = scanner.scan_market(symbols, interval='1h')
    
    print("\nScan Summary:")
    print(f"Total records returned: {len(results_df)}")
    
    if not results_df.empty:
        pine_buys = results_df[results_df['Pine Signal'] == 'BUY']
        print(f"Pine BUY signals: {len(pine_buys)}")
        
        print("\nFirst 5 records 'Pine Signal' values:")
        print(results_df['Pine Signal'].head().tolist())
        
        # Check why they might be failing
        sample = results_df.iloc[0]
        print("\nSample Data Point Metrics:")
        metrics = ['LTP', 'Stoch RSI K', 'SMI', 'MACD', 'EMA5', 'EMA9', 'EMA21']
        for m in metrics:
            if m in sample:
                print(f"{m}: {sample[m]}")
    else:
        print("No results returned.")

if __name__ == "__main__":
    test_scan()
