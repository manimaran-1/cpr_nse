import pandas as pd
import requests
import io
import pytz
import logging
import os
import time
import hashlib
import pickle
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
import json
import urllib.request
import urllib.error
import zipfile
import yfinance as yf

# Fix TzCache permission errors on Streamlit Cloud — use project cache dir
_tz_cache_dir = os.path.join(os.path.dirname(__file__), "cache", "tz_cache")
os.makedirs(_tz_cache_dir, exist_ok=True)
try:
    yf.set_tz_cache_location(_tz_cache_dir)
except Exception:
    pass

# Suppress yfinance's noisy stderr logging for missing/delisted symbols
yf_logger = logging.getLogger("yfinance")
yf_logger.setLevel(logging.CRITICAL)

# Configuration for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Define IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Symbol aliases — stocks renamed on NSE/Yahoo
SYMBOL_ALIASES = {
    "ZOMATO": "ETERNAL",
    "8K": "8KMILES",
}

# ============================================================
# CACHE SYSTEM
# ============================================================
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
OHLCV_CACHE_DIR = os.path.join(CACHE_DIR, "ohlcv")
BHAVCOPY_CACHE_DIR = os.path.join(CACHE_DIR, "bhavcopy")
CACHE_EXPIRY_HOURS = 24
OHLCV_CACHE_MINUTES = 5  # OHLCV data cached for 5 min during market hours

# Ensure cache dirs exist at import time
for _d in [CACHE_DIR, OHLCV_CACHE_DIR, BHAVCOPY_CACHE_DIR]:
    os.makedirs(_d, exist_ok=True)


def _ohlcv_cache_key(symbol, resolution, range_from, range_to):
    """Generate a unique, filesystem-safe cache key."""
    raw = f"{symbol}|{resolution}|{range_from}|{range_to}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_ohlcv_cache(symbol, resolution, range_from, range_to):
    """Return cached DataFrame if valid, else None. Uses parquet for safety."""
    key = _ohlcv_cache_key(symbol, resolution, range_from, range_to)
    parquet_path = os.path.join(OHLCV_CACHE_DIR, f"{key}.parquet")
    pkl_path = os.path.join(OHLCV_CACHE_DIR, f"{key}.pkl")

    cache_path = None
    if os.path.exists(parquet_path):
        cache_path = parquet_path
    elif os.path.exists(pkl_path):
        cache_path = pkl_path

    if cache_path is None:
        return None

    age_sec = time.time() - os.path.getmtime(cache_path)
    now_ist = datetime.now(IST)
    market_open = now_ist.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if market_open <= now_ist <= market_close:
        max_age = OHLCV_CACHE_MINUTES * 60
    else:
        max_age = 3600  # 1 hour outside market

    if age_sec < max_age:
        try:
            if cache_path.endswith('.parquet'):
                return pd.read_parquet(cache_path)
            else:
                # Migrate old pickle to parquet
                df = pickle.load(open(cache_path, "rb"))
                try:
                    df.to_parquet(parquet_path)
                    os.remove(pkl_path)
                except Exception:
                    pass
                return df
        except Exception:
            return None
    return None


def _set_ohlcv_cache(symbol, resolution, range_from, range_to, df):
    """Persist DataFrame to disk cache using parquet format."""
    key = _ohlcv_cache_key(symbol, resolution, range_from, range_to)
    parquet_path = os.path.join(OHLCV_CACHE_DIR, f"{key}.parquet")
    try:
        df.to_parquet(parquet_path)
    except Exception as e:
        logger.debug(f"Cache write failed for {symbol}: {e}")


# ============================================================
# SYMBOL LIST FETCHING (with 24h cache)
# ============================================================

def get_cached_file(filename):
    """Checks if a valid, non-expired cache file exists."""
    cache_path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(cache_path):
        file_age = time.time() - os.path.getmtime(cache_path)
        if file_age < (CACHE_EXPIRY_HOURS * 3600):
            return cache_path
    return None

def save_to_cache(filename, content):
    """Saves content to the local cache directory."""
    try:
        cache_path = os.path.join(CACHE_DIR, filename)
        with open(cache_path, "wb") as f:
            f.write(content)
        return cache_path
    except Exception as e:
        logger.error(f"Failed to save {filename} to cache: {e}")
        return None

# Persistent HTTP session for all web requests
_http_session = requests.Session()
_http_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.nseindia.com/',
})

def fetch_with_cache(url, filename):
    """Fetches a CSV from a URL with 24h local caching and resilient failover."""
    cached_path = get_cached_file(filename)

    if cached_path:
        logger.info(f"Using cached symbol list: {filename}")
        try:
            return pd.read_csv(cached_path)
        except Exception as e:
            logger.error(f"Error reading cache {filename}: {e}. Attempting fresh download.")

    try:
        logger.info(f"Fetching fresh symbols from {url}...")
        response = _http_session.get(url, timeout=10)
        response.raise_for_status()
        save_to_cache(filename, response.content)
        return pd.read_csv(io.StringIO(response.content.decode('utf-8')))
    except Exception as e:
        logger.error(f"Web fetch failed for {url}: {e}")
        fallback_path = os.path.join(CACHE_DIR, filename)
        if os.path.exists(fallback_path):
            logger.warning(f"Network error. Falling back to EXPIRED cache: {filename}")
            return pd.read_csv(fallback_path)
        raise

def _extract_symbols(df):
    """Common helper: extract and filter symbols from an NSE CSV DataFrame."""
    symbols = [str(sym).strip() for sym in df['Symbol'].tolist()
               if "DUMMY" not in str(sym).upper() and str(sym).strip()]
    return [f"NSE:{sym}-EQ" for sym in symbols]


def get_nifty50_symbols():
    """Fetches Nifty 50 symbols from NSE Archives (with cache)."""
    try:
        df = fetch_with_cache(
            "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
            "nifty50.csv"
        )
        return _extract_symbols(df)
    except Exception as e:
        logger.error(f"Error fetching Nifty 50: {e}")
    return ["NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ"]


def get_nifty200_symbols():
    """Fetches Nifty 200 symbols from NSE Archives (with cache)."""
    try:
        df = fetch_with_cache(
            "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
            "nifty200.csv"
        )
        return _extract_symbols(df)
    except Exception:
        return get_nifty500_symbols()[:200]


def get_nifty500_symbols():
    """Fetches Nifty 500 symbols from NSE Archives (with cache)."""
    try:
        df = fetch_with_cache(
            "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
            "nifty500.csv"
        )
        return _extract_symbols(df)
    except Exception as e:
        logger.error(f"Fatal error fetching Nifty 500: {e}")
    return ["NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ"]


def get_total_cash_segment():
    """Fetches ALL NSE-listed equities (~2000+ stocks) from EQUITY_L.csv."""
    try:
        df = fetch_with_cache(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            "equity_l.csv"
        )
        col = 'SYMBOL' if 'SYMBOL' in df.columns else 'Symbol'
        symbols = [str(sym).strip() for sym in df[col].tolist()
                   if "DUMMY" not in str(sym).upper()
                   and str(sym).strip()
                   and not str(sym).startswith('NIFTY')]
        return [f"NSE:{sym}-EQ" for sym in symbols]
    except Exception as e:
        logger.error(f"Error fetching Total Cash Segment: {e}")
        return get_nifty500_symbols()

def get_index_constituents(index_name):
    """Fetches symbols for a specific index by name (with cache)."""
    if index_name == "Nifty 50":
        return get_nifty50_symbols()
    if index_name == "Nifty 200":
        return get_nifty200_symbols()
    if index_name == "Nifty 500":
        return get_nifty500_symbols()
    if index_name == "Total Cash Segment":
        return get_total_cash_segment()

    slugs = {
        "Nifty 100": "nifty100",
        "Nifty Next 50": "niftynext50",
        "Nifty Bank": "niftybank",
        "Nifty Auto": "niftyauto",
        "Nifty IT": "niftyit",
        "Nifty PSU Bank": "niftypsubank",
        "Nifty Fin Service": "niftyfinancelist",
        "Nifty Pharma": "niftypharma",
        "Nifty FMCG": "niftyfmcg",
        "Nifty Metal": "niftymetal",
        "Nifty Media": "niftymedia",
        "Nifty Energy": "niftyenergy",
        "Nifty Realty": "niftyrealty",
        "Nifty Healthcare": "niftyhealthcare",
        "Nifty Private Bank": "niftyprivatebank",
        "Nifty Consumption": "niftyconsumption",
        "Nifty Microcap 250": "niftymicrocap250",
        "Nifty Midcap 150": "niftymidcap150",
        "Nifty Midcap 100": "niftymidcap100",
        "Nifty Midcap 50": "niftymidcap50",
        "Nifty Smallcap 250": "niftysmallcap250",
        "Nifty Smallcap 100": "niftysmallcap100",
        "Nifty Smallcap 50": "niftysmallcap50",
        "Nifty Commodities": "niftycommodities",
        "Nifty CPSE": "niftycpse",
        "Nifty Infrastructure": "niftyinfrastructure",
        "Nifty MNC": "niftymnc",
        "Nifty PSE": "niftypse",
        "Nifty Services Sector": "niftyservicesector",
        "Nifty Dividend Opp 50": "niftydividendopportunities50",
        "Nifty Growth Sect 15": "niftygrowthsectors15",
        "Nifty100 Quality 30": "nifty100quality30",
    }

    if index_name in slugs:
        slug = slugs[index_name]
        try:
            url = f"https://archives.nseindia.com/content/indices/ind_{slug}list.csv"
            filename = f"{slug}.csv"
            df = fetch_with_cache(url, filename)
            return _extract_symbols(df)
        except Exception as e:
            logger.warning(f"Could not fetch {index_name}: {e}")

    logger.warning(f"Unknown index '{index_name}', falling back to Nifty 50")
    return get_nifty50_symbols()

def get_all_indices_dict():
    """Returns a dictionary of all supported NSE Indices."""
    return {
        "Nifty 50": "Nifty 50",
        "Nifty Next 50": "Nifty Next 50",
        "Nifty 100": "Nifty 100",
        "Nifty 200": "Nifty 200",
        "Nifty 500": "Nifty 500",
        "Total Cash Segment (~2000+)": "Total Cash Segment",
        "Nifty Bank": "Nifty Bank",
        "Nifty Auto": "Nifty Auto",
        "Nifty IT": "Nifty IT",
        "Nifty PSU Bank": "Nifty PSU Bank",
        "Nifty Private Bank": "Nifty Private Bank",
        "Nifty Fin Service": "Nifty Fin Service",
        "Nifty Pharma": "Nifty Pharma",
        "Nifty Healthcare": "Nifty Healthcare",
        "Nifty FMCG": "Nifty FMCG",
        "Nifty Metal": "Nifty Metal",
        "Nifty Media": "Nifty Media",
        "Nifty Energy": "Nifty Energy",
        "Nifty Realty": "Nifty Realty",
        "Nifty Consumption": "Nifty Consumption",
        "Nifty Midcap 50": "Nifty Midcap 50",
        "Nifty Midcap 100": "Nifty Midcap 100",
        "Nifty Midcap 150": "Nifty Midcap 150",
        "Nifty Smallcap 50": "Nifty Smallcap 50",
        "Nifty Smallcap 100": "Nifty Smallcap 100",
        "Nifty Smallcap 250": "Nifty Smallcap 250",
        "Nifty Microcap 250": "Nifty Microcap 250",
        "Nifty Commodities": "Nifty Commodities",
        "Nifty CPSE": "Nifty CPSE",
        "Nifty Infrastructure": "Nifty Infrastructure",
        "Nifty MNC": "Nifty MNC",
        "Nifty PSE": "Nifty PSE",
        "Nifty Services Sector": "Nifty Services Sector",
        "Nifty Dividend Opp 50": "Nifty Dividend Opp 50",
        "Nifty Growth Sect 15": "Nifty Growth Sect 15",
        "Nifty100 Quality 30": "Nifty100 Quality 30",
    }


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol):
    """Normalizes symbol to internal format (NSE:SYMBOL-EQ) or (NSE:INDEX-INDEX)."""
    symbol = symbol.strip().upper()

    index_map = {
        "^NSEI": "NSE:NIFTY50-INDEX",
        "NIFTY": "NSE:NIFTY50-INDEX",
        "^NSEBANK": "NSE:NIFTYBANK-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "NIFTY50": "NSE:NIFTY50-INDEX",
        "NIFTYBANK": "NSE:NIFTYBANK-INDEX"
    }
    if symbol in index_map:
        return index_map[symbol]

    if ":" in symbol and "-" in symbol:
        return symbol

    symbol = symbol.replace(".NS", "").replace(".BO", "")
    return f"NSE:{symbol}-EQ"


def nse_to_yahoo(nse_symbol):
    """Convert NSE format (NSE:RELIANCE-EQ) to Yahoo Finance format (RELIANCE.NS)."""
    sym = nse_symbol.upper()
    # Handle index symbols
    if "NIFTY50" in sym:
        return "^NSEI"
    if "NIFTYBANK" in sym:
        return "^NSEBANK"
    # Handle equity symbols: NSE:RELIANCE-EQ -> RELIANCE.NS
    if ":" in sym:
        sym = sym.split(":")[1]
    sym = sym.replace("-EQ", "").replace("-INDEX", "")
    # Apply symbol aliases for renamed stocks (e.g. ZOMATO -> ETERNAL)
    if sym in SYMBOL_ALIASES:
        sym = SYMBOL_ALIASES[sym]
    return f"{sym}.NS"


_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_YF_TIMEOUT = 15


def _yf_fetch_chart(yf_symbol, interval='1h', range_str='60d'):
    """Fetch raw Yahoo Finance chart data via direct API."""
    url = f"{_YF_BASE}/{yf_symbol}?interval={interval}&range={range_str}"
    req = urllib.request.Request(url, headers={"User-Agent": _YF_UA})
    try:
        with urllib.request.urlopen(req, timeout=_YF_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["chart"]["result"][0]
    except Exception as e:
        logger.debug(f"Yahoo Finance API error for {yf_symbol}: {e}")
        return None


def fetch_data_yfinance(symbol, interval='1h', period='60d'):
    """Fetch OHLCV data from Yahoo Finance direct API (single HTTP request per symbol)."""
    try:
        yf_symbol = nse_to_yahoo(symbol)

        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m',
            '30m': '30m', '60m': '60m', '1h': '1h',
            '1d': '1d', 'D': '1d', 'W': '1wk', 'M': '1mo',
        }
        yf_interval = interval_map.get(interval, '1h')

        if yf_interval == '1m':
            range_str = '5d'
        elif yf_interval in ['5m', '15m', '30m', '60m', '1h']:
            range_str = '60d'
        else:
            range_str = '2y'

        chart_result = _yf_fetch_chart(yf_symbol, interval=yf_interval, range_str=range_str)

        if chart_result is None:
            return pd.DataFrame()

        timestamps = chart_result.get("timestamp", [])
        indicators = chart_result.get("indicators", {}).get("quote", [{}])[0]

        if not timestamps:
            return pd.DataFrame()

        df = pd.DataFrame({
            'open': indicators.get('open', []),
            'high': indicators.get('high', []),
            'low': indicators.get('low', []),
            'close': indicators.get('close', []),
            'volume': indicators.get('volume', []),
        })

        df.index = pd.to_datetime(timestamps, unit='s')
        df.index = df.index.tz_localize('UTC').tz_convert(IST)

        df = df.dropna(subset=['close'])

        if df.empty:
            return pd.DataFrame()

        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
        df['volume'] = df['volume'].fillna(0).astype(int)

        return df

    except Exception as e:
        logger.warning(f"Yahoo Finance error for {symbol}: {e}")
        return pd.DataFrame()


def fetch_data_yf_lib(symbol, interval='1h', period='60d'):
    """Fetch OHLCV data using yfinance library (multiple HTTP requests per symbol)."""
    try:
        yf_symbol = nse_to_yahoo(symbol)

        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m',
            '30m': '30m', '60m': '60m', '1h': '1h',
            '1d': '1d', 'D': '1d', 'W': '1wk', 'M': '1mo',
        }
        yf_interval = interval_map.get(interval, '1h')

        if yf_interval == '1m':
            period = '5d'
        elif yf_interval in ['5m', '15m', '30m', '60m', '1h']:
            period = '60d'
        else:
            period = '2y'

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=yf_interval)

        if df.empty:
            return pd.DataFrame()

        df.columns = [c.lower() for c in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']].copy()

        if df.index.tz is not None:
            if str(df.index.tz) != 'Asia/Kolkata':
                df.index = df.index.tz_convert(IST)
        else:
            df.index = df.index.tz_localize('UTC').tz_convert(IST)

        return df

    except Exception as e:
        logger.warning(f"yfinance library error for {symbol}: {e}")
        return pd.DataFrame()


# ============================================================
# DATA SOURCE MANAGEMENT
# ============================================================

_DATA_SOURCE_MAP = {
    "auto": "yahoo",
    "yahoo": "yahoo",
    "yfapi": "yahoo",
    "yfinance": "yfinance",
    "yflib": "yfinance",
}

_active_data_source = "yahoo"


def set_data_source(source):
    """Set the active data source. Called from Streamlit UI or CLI."""
    global _active_data_source
    ds = _DATA_SOURCE_MAP.get(source.lower(), "yahoo")
    _active_data_source = ds
    logger.info(f"Data source set to: {ds}")


def get_data_source():
    """Get the current active data source."""
    return _active_data_source


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_data(symbol, period='1y', interval='1d', retries=2, timeout=10, data_source=None):
    """
    Fetches historical OHLCV data.
    Checks disk cache first, then tries primary source, then falls back.
    """
    symbol = normalize_symbol(symbol)

    ds = data_source or _active_data_source
    ds = _DATA_SOURCE_MAP.get(ds.lower() if ds else "yahoo", "yahoo")

    # Check disk cache first — avoids redundant network requests
    res_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60', '1h': '60', '1d': 'D'}
    resolution = res_map.get(interval, 'D')
    range_to = datetime.now().strftime("%Y-%m-%d")
    range_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    cached = _get_ohlcv_cache(symbol, resolution, range_from, range_to)
    if cached is not None:
        return cached

    # Try primary source (direct API is 1 request per symbol, more reliable)
    if ds == "yahoo":
        df = fetch_data_yfinance(symbol, interval=interval)
    else:
        df = fetch_data_yf_lib(symbol, interval=interval)

    if not df.empty:
        _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
        return df

    # Fallback: if primary failed, try the other source
    if ds == "yahoo":
        logger.debug(f"Yahoo direct API failed for {symbol}, trying yfinance library...")
        df = fetch_data_yf_lib(symbol, interval=interval)
    else:
        logger.debug(f"yfinance library failed for {symbol}, trying Yahoo direct API...")
        df = fetch_data_yfinance(symbol, interval=interval)

    if not df.empty:
        _set_ohlcv_cache(symbol, resolution, range_from, range_to, df)
        return df

    return pd.DataFrame()


def fetch_data_batch(symbols, interval='1h', max_workers=4, progress_callback=None, phase_label=""):
    """Batch fetch OHLCV data with rate limiting to avoid Yahoo Finance blocks."""
    t0 = time.time()
    results = {}
    total = len(symbols)
    ds = _active_data_source
    logger.info(f"Batch fetch: {total} symbols ({ds}, {max_workers} workers)")

    def _fetch_one(sym):
        # Small delay to avoid rate limiting
        time.sleep(0.2)
        df = fetch_data(sym, interval=interval, data_source=ds)
        return sym, df

    done_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in concurrent.futures.as_completed(futures):
            try:
                sym, df = future.result(timeout=60)
                if df is not None and not df.empty:
                    results[sym] = df
            except Exception as e:
                sym = futures[future]
                logger.warning(f"Failed to fetch {sym}: {e}")
            done_count += 1
            if progress_callback and done_count % 50 == 0:
                progress_callback(done_count, total, phase_label)

    elapsed = time.time() - t0
    logger.info(f"Batch complete: {len(results)}/{total} symbols in {elapsed:.1f}s")
    return results


def is_market_open():
    """Check if NSE market is currently open (Mon-Fri, 9:15-15:30 IST)."""
    now = datetime.now(IST)
    if now.weekday() > 4:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def clear_ohlcv_cache():
    """Clears all OHLCV cache files (parquet and legacy pickle)."""
    count = 0
    for f in os.listdir(OHLCV_CACHE_DIR):
        if f.endswith(('.parquet', '.pkl')):
            try:
                os.remove(os.path.join(OHLCV_CACHE_DIR, f))
                count += 1
            except Exception:
                pass
    logger.info(f"Cleared {count} OHLCV cache files")
    return count


# Module level cache for preloaded Bhavcopy lookup dictionaries to avoid redundant disk read/writes
_bhavcopy_memory_cache = {}

def load_bhavcopy_lookup(date_val):
    """
    Downloads and caches the official NSE Bhavcopy for the specified date,
    then returns a fast dictionary lookup: Ticker -> details.

    Returns:
        dict: Ticker symbol (str) -> dict of OHLCV + ltp, or None if failed.
    """
    global _bhavcopy_memory_cache

    # Normalize to datetime.date
    if isinstance(date_val, datetime):
        d_key = date_val.date()
    elif hasattr(date_val, 'date'):
        d_key = date_val.date()
    else:
        d_key = date_val

    if d_key in _bhavcopy_memory_cache:
        logger.debug(f"Bhavcopy memory cache hit for {d_key}")
        return _bhavcopy_memory_cache[d_key]

    dt_str = d_key.strftime("%Y%m%d")
    cache_path = os.path.join(BHAVCOPY_CACHE_DIR, f"BhavCopy_NSE_CM_0_0_0_{dt_str}_F_0000.csv.zip")

    # 1. Check if ZIP already exists in local cache
    if os.path.exists(cache_path):
        logger.info(f"Using cached Bhavcopy for {d_key}")
        try:
            lookup = _parse_bhavcopy_zip(cache_path)
            if lookup:
                _bhavcopy_memory_cache[d_key] = lookup
                return lookup
        except Exception as e:
            logger.warning(f"Failed parsing cached Bhavcopy for {d_key}: {e}. Retrying download.")

    # 2. Download from NSE archives
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{dt_str}_F_0000.csv.zip"
    logger.info(f"Downloading Bhavcopy from exchange for {d_key}...")

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
        })
        with urllib.request.urlopen(req, timeout=12) as response:
            zip_data = response.read()

        # Write to disk cache
        with open(cache_path, "wb") as f:
            f.write(zip_data)

        lookup = _parse_bhavcopy_zip(cache_path)
        if lookup:
            _bhavcopy_memory_cache[d_key] = lookup
            return lookup

    except Exception as e:
        logger.warning(f"Bhavcopy download/parse failed for {d_key}: {e}")

    return None

def _parse_bhavcopy_zip(zip_path):
    """Parses downloaded Bhavcopy ZIP file into a standard lookup dictionary."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            files = z.namelist()
            with z.open(files[0]) as f:
                df = pd.read_csv(f)

        # Strip whitespaces from column names
        df.columns = [c.strip() for c in df.columns]

        # Verify required columns exist (clean column mapping)
        required_cols = ['TckrSymb', 'OpnPric', 'HghPric', 'LwPric', 'ClsPric', 'LastPric', 'TtlTradgVol']
        for col in required_cols:
            if col not in df.columns:
                logger.error(f"Required Bhavcopy column {col} missing! Found: {df.columns.tolist()[:10]}")
                return None

        # Build dictionary lookup
        lookup = {}
        for _, row in df.iterrows():
            sym = str(row['TckrSymb']).strip()
            lookup[sym] = {
                'open': float(row['OpnPric']),
                'high': float(row['HghPric']),
                'low': float(row['LwPric']),
                'close': float(row['ClsPric']),
                'ltp': float(row['LastPric']),
                'volume': int(row['TtlTradgVol']),
            }
        return lookup
    except Exception as e:
        logger.error(f"Error parsing Bhavcopy ZIP: {e}")
        return None
