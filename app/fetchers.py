"""Data sources: Upstox (preferred) + Yahoo fallback + MrChartist (free FII/DII)."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from app.config import INSTRUMENTS, MRCHARTIST_DATA, UPSTOX_ACCESS_TOKEN, UPSTOX_BASE, YAHOO

log = logging.getLogger(__name__)
UA = {"User-Agent": "PremarketDashboard/1.0", "Accept": "application/json"}


# ── Yahoo (always free, no key) ──────────────────────────────
def yahoo_quote(symbol: str) -> float | None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol, safe='')}?interval=1d&range=5d"
    )
    try:
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code != 200:
            return None
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for c in reversed(closes):
            if c is not None:
                return float(c)
        p = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
        return float(p) if p is not None else None
    except Exception as e:
        log.warning("Yahoo %s: %s", symbol, e)
        return None


def fetch_yahoo_all() -> dict[str, float | None]:
    return {k: yahoo_quote(sym) for k, sym in YAHOO.items()}


# ── Upstox ───────────────────────────────────────────────────
def upstox_enabled() -> bool:
    return bool(UPSTOX_ACCESS_TOKEN)


def upstox_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    }


def upstox_quotes(keys: list[str]) -> dict[str, dict[str, Any]]:
    """Full market quotes for instrument keys. Returns map instrument_key → quote dict."""
    if not upstox_enabled() or not keys:
        return {}
    # Upstox allows comma-separated instrument_key
    joined = ",".join(keys)
    url = f"{UPSTOX_BASE}/market-quote/quotes"
    try:
        r = requests.get(
            url,
            headers=upstox_headers(),
            params={"instrument_key": joined},
            timeout=20,
        )
        if r.status_code != 200:
            log.warning("Upstox quotes HTTP %s: %s", r.status_code, r.text[:300])
            return {}
        data = (r.json().get("data") or {})
        # Keys in response may use colon instead of pipe
        out: dict[str, dict] = {}
        for k, v in data.items():
            out[k] = v
            # also store normalized with |
            out[k.replace(":", "|")] = v
        return out
    except Exception as e:
        log.exception("Upstox quotes: %s", e)
        return {}


def extract_ltp(q: dict | None) -> float | None:
    if not q:
        return None
    for path in (
        ("last_price",),
        ("ltp",),
        ("ohlc", "close"),
        ("close",),
    ):
        cur: Any = q
        ok = True
        for p in path:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok and cur is not None:
            try:
                return float(cur)
            except (TypeError, ValueError):
                pass
    return None


def extract_prev_close(q: dict | None) -> float | None:
    if not q:
        return None
    for key in ("close_price", "previous_close", "prev_close"):
        if q.get(key) is not None:
            try:
                return float(q[key])
            except (TypeError, ValueError):
                pass
    ohlc = q.get("ohlc") or {}
    if ohlc.get("close") is not None:
        try:
            return float(ohlc["close"])
        except (TypeError, ValueError):
            pass
    return extract_ltp(q)


def fetch_upstox_all() -> dict[str, float | None]:
    keys = list(INSTRUMENTS.values())
    raw = upstox_quotes(keys)
    out: dict[str, float | None] = {}
    for name, ikey in INSTRUMENTS.items():
        q = raw.get(ikey) or raw.get(ikey.replace("|", ":"))
        # Prefer LTP for live (GIFT), close for indices after hours
        ltp = extract_ltp(q)
        prev = extract_prev_close(q)
        if name == "gift":
            out[name] = ltp or prev
        else:
            # last session reference: prev close preferred for gap base
            out[name] = prev or ltp
        out[f"{name}_ltp"] = ltp
        out[f"{name}_prev"] = prev
    return out


# ── MrChartist (free FII/DII — no key, no bill) ──────────────
def fetch_mrchartist() -> dict[str, Any] | None:
    try:
        r = requests.get(MRCHARTIST_DATA, headers=UA, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        log.warning("MrChartist: %s", e)
        return None


def parse_fii_date(s: str | None) -> str | None:
    if not s:
        return None
    months = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }
    parts = str(s).replace(",", "").split("-")
    if len(parts) != 3:
        return None
    try:
        day, mon_s, year = int(parts[0]), parts[1][:3], int(parts[2])
        mon = months.get(mon_s)
        if not mon:
            return None
        return f"{year:04d}-{mon:02d}-{day:02d}"
    except ValueError:
        return None
