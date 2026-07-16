"""Data sources: Upstox (preferred) + Yahoo fallback + MrChartist (free FII/DII)."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from app.config import INSTRUMENTS, MRCHARTIST_DATA, UPSTOX_ACCESS_TOKEN, UPSTOX_BASE, YAHOO

log = logging.getLogger(__name__)
UA = {"User-Agent": "PremarketDashboard/1.0", "Accept": "application/json"}


def format_price_chg(price: float | None, chg_pct: float | None, digits: int = 2) -> str | None:
    """24078.50 (+0.11%) style — actual day change % in brackets."""
    if price is None:
        return None
    p = f"{price:,.{digits}f}"
    if chg_pct is None:
        return p
    sign = "+" if chg_pct > 0 else ""
    return f"{p} ({sign}{chg_pct:.2f}%)"


def _chg_pct(price: float | None, prev: float | None) -> float | None:
    if price is None or prev is None or prev == 0:
        return None
    return round(100.0 * (price - prev) / prev, 2)


def _chg_abs(price: float | None, prev: float | None) -> float | None:
    if price is None or prev is None:
        return None
    return round(price - prev, 4)


# ── Yahoo (always free, no key) ──────────────────────────────
def yahoo_quote(symbol: str) -> dict[str, float | None] | None:
    """Return {price, prev, chg, chg_pct} for a Yahoo symbol."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol, safe='')}?interval=1d&range=10d"
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

        # last two non-null closes
        non_null = [float(c) for c in closes if c is not None]
        last = non_null[-1] if non_null else None
        prev_close = non_null[-2] if len(non_null) >= 2 else None

        # Prefer meta when available (intraday accurate)
        price = meta.get("regularMarketPrice")
        if price is not None:
            price = float(price)
        else:
            price = last

        chart_prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if chart_prev is not None:
            prev = float(chart_prev)
        else:
            prev = prev_close

        # If price is last close and prev is chartPreviousClose, good for closed session.
        # If only one close, try previousClose from meta only.
        chg_pct = _chg_pct(price, prev)
        chg = _chg_abs(price, prev)

        # meta sometimes has regularMarketChangePercent already (fraction or %)
        meta_chg = meta.get("regularMarketChangePercent")
        if meta_chg is not None and chg_pct is None:
            try:
                mc = float(meta_chg)
                # Yahoo chart meta often stores as percent points already in some feeds
                chg_pct = round(mc if abs(mc) < 50 else mc, 2)
            except (TypeError, ValueError):
                pass

        return {
            "price": price,
            "prev": prev,
            "chg": chg,
            "chg_pct": chg_pct,
            "display": format_price_chg(price, chg_pct),
        }
    except Exception as e:
        log.warning("Yahoo %s: %s", symbol, e)
        return None


def fetch_yahoo_all() -> dict[str, Any]:
    """Map name → quote dict (price/prev/chg_pct/display)."""
    out: dict[str, Any] = {}
    for k, sym in YAHOO.items():
        q = yahoo_quote(sym)
        if not q:
            out[k] = None
            continue
        out[k] = q["price"]
        out[f"{k}_prev"] = q["prev"]
        out[f"{k}_chg"] = q["chg"]
        out[f"{k}_chg_pct"] = q["chg_pct"]
        out[f"{k}_display"] = q["display"]
    return out


# ── Upstox ───────────────────────────────────────────────────
def upstox_enabled() -> bool:
    return bool(UPSTOX_ACCESS_TOKEN)


def upstox_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    }


def upstox_quotes(keys: list[str]) -> dict[str, dict[str, Any]]:
    if not upstox_enabled() or not keys:
        return {}
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
        data = r.json().get("data") or {}
        out: dict[str, dict] = {}
        for k, v in data.items():
            out[k] = v
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
        ("net_change",),  # skip
    ):
        if path[0] == "net_change":
            continue
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
    for key in ("close_price", "previous_close", "prev_close", "cp"):
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
    return None


def extract_net_change_pct(q: dict | None) -> float | None:
    """Upstox often exposes net_change / percentage fields."""
    if not q:
        return None
    for key in ("percentage_change", "pChange", "net_change_percentage", "change_percent"):
        if q.get(key) is not None:
            try:
                return round(float(q[key]), 2)
            except (TypeError, ValueError):
                pass
    # compute from last + prev
    ltp = extract_ltp(q)
    prev = extract_prev_close(q)
    return _chg_pct(ltp, prev)


def fetch_upstox_all() -> dict[str, Any]:
    keys = list(INSTRUMENTS.values())
    raw = upstox_quotes(keys)
    out: dict[str, Any] = {}
    for name, ikey in INSTRUMENTS.items():
        q = raw.get(ikey) or raw.get(ikey.replace("|", ":"))
        ltp = extract_ltp(q)
        prev = extract_prev_close(q)
        # Prefer live LTP when available (esp. GIFT)
        price = ltp or prev
        chg_pct = extract_net_change_pct(q)
        if chg_pct is None:
            chg_pct = _chg_pct(price, prev)
        chg = _chg_abs(price, prev)
        out[name] = price
        out[f"{name}_ltp"] = ltp
        out[f"{name}_prev"] = prev
        out[f"{name}_chg"] = chg
        out[f"{name}_chg_pct"] = chg_pct
        out[f"{name}_display"] = format_price_chg(price, chg_pct)
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
