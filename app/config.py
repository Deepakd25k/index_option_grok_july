from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# On Vercel the filesystem is read-only except /tmp
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = Path("/tmp/premarket-data")
else:
    DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_FILE = DATA_DIR / "latest.json"
DAILY_FILE = DATA_DIR / "daily_history.json"
WEEKLY_FILE = DATA_DIR / "weekly_history.json"

UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
UPSTOX_BASE = "https://api.upstox.com/v2"

# Retention — free local disk, no cloud bill
DAILY_RETENTION_DAYS = int(os.getenv("DAILY_RETENTION_DAYS", "90"))
WEEKLY_RETENTION_WEEKS = int(os.getenv("WEEKLY_RETENTION_WEEKS", "104"))

GAP_SMALL_PCT = float(os.getenv("GAP_SMALL_PCT", "0.30"))
GAP_MEDIUM_PCT = float(os.getenv("GAP_MEDIUM_PCT", "0.70"))

# Upstox instrument keys (official)
INSTRUMENTS = {
    "nifty": "NSE_INDEX|Nifty 50",
    "banknifty": "NSE_INDEX|Nifty Bank",
    "vix": "NSE_INDEX|India VIX",
    "gift": "GLOBAL_INDEX|SGX NIFTY",  # GIFT Nifty — auto, no paste
    "dow": "GLOBAL_INDEX|^DJI",
    "spx": "GLOBAL_INDEX|^GSPC",
    "nasdaq": "GLOBAL_INDEX|IXIX",  # US Tech 100 on Upstox
    "nikkei": "GLOBAL_INDEX|^N225",
    "hsi": "GLOBAL_INDEX|^HSI",
}

# Yahoo fallback symbols (free, no token)
YAHOO = {
    "nifty": "^NSEI",
    "banknifty": "^NSEBANK",
    "vix": "^INDIAVIX",
    "dow": "^DJI",
    "spx": "^GSPC",
    "nasdaq": "^IXIC",
    "nikkei": "^N225",
    "hsi": "^HSI",
    # Europe (Yahoo free)
    "ftse": "^FTSE",
    "dax": "^GDAXI",
    "cac": "^FCHI",
    "stoxx50": "^STOXX50E",
    # GIFT not reliable on Yahoo free
}

# Column schema for Daily Log (stable order)
DAILY_COLUMNS = [
    "date",
    "day",
    "is_trading",
    "holiday",
    "nifty",
    "banknifty",
    "vix",
    "gift",
    "gap_pts",
    "gap_pct",
    "gap_category",
    "dow",
    "spx",
    "nasdaq",
    "nikkei",
    "hsi",
    "ftse",
    "dax",
    "cac",
    "stoxx50",
    "fii_cash_net",
    "dii_cash_net",
    "fii_idx_fut_long",
    "fii_idx_fut_short",
    "fii_idx_fut_long_pct",
    "fii_idx_fut_short_pct",
    "fii_idx_fut_long_display",
    "fii_idx_fut_short_display",
    "fii_idx_fut_net",
    "fii_idx_fut_ratio",
    "fii_idx_opt_pcr_short",
    "dii_idx_fut_long_display",
    "dii_idx_fut_short_display",
    "pcr",
    "sentiment",
    "oi_date",
    "last_updated",
    "sources",
]

MRCHARTIST_DATA = "https://fii-diidata.mrchartist.com/api/data"

NSE_HOLIDAYS_2026 = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
