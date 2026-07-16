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
    """24078.50 (+0.11%) style — actual day change % in brackets.

    Never invent a percent; if unknown, show price only.
    """
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


def _nearly_eq(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.05, abs(b) * 1e-6)


# ── Yahoo (always free, no key) ──────────────────────────────
def yahoo_quote(symbol: str) -> dict[str, float | None] | None:
    """Return {price, prev, chg, chg_pct, display}.

    Day % is always vs the **previous daily session close** from the OHLC
    series. This avoids chartPreviousClose bugs that equal live price → (0.00%).
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(symbol, safe='')}?interval=1d&range=1mo"
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

        sessions = [float(c) for c in closes if c is not None]
        if not sessions:
            return None

        last_close = sessions[-1]
        prev_close = sessions[-2] if len(sessions) >= 2 else None

        rmp = meta.get("regularMarketPrice")
        live = float(rmp) if rmp is not None else None
        price = live if live is not None else last_close

        # ── Resolve previous session close ────────────────────
        # Primary: second-last daily candle (true prior session)
        ref = prev_close

        meta_prev_raw = meta.get("previousClose") or meta.get("chartPreviousClose")
        meta_prev = float(meta_prev_raw) if meta_prev_raw is not None else None

        if live is not None and prev_close is not None:
            if _nearly_eq(live, last_close):
                # Settled on last bar (market closed / last print = close)
                price = last_close
                ref = prev_close
            else:
                # Live market: last bar is usually *today's* developing candle
                # → prior session = prev_close.
                # Exception: pre-open / last bar still yesterday → prior = last_close
                if meta_prev is not None and _nearly_eq(last_close, meta_prev):
                    ref = last_close
                else:
                    ref = prev_close
        elif prev_close is not None:
            price = last_close
            ref = prev_close

        # Safety: if ref collapsed to same as price but candles differ, use candle day-move
        if (
            ref is not None
            and prev_close is not None
            and _nearly_eq(price, ref)
            and not _nearly_eq(last_close, prev_close)
        ):
            price = last_close
            ref = prev_close

        # Last resort: meta previousClose if still no ref
        if ref is None and meta_prev is not None and not _nearly_eq(price, meta_prev):
            ref = meta_prev

        chg_pct = _chg_pct(price, ref)
        chg = _chg_abs(price, ref)

        # If still zero but last two candles differ, force candle-based day change
        if (
            chg_pct == 0.0
            and prev_close is not None
            and not _nearly_eq(last_close, prev_close)
        ):
            price = last_close
            ref = prev_close
            chg_pct = _chg_pct(price, ref)
            chg = _chg_abs(price, ref)

        return {
            "price": price,
            "prev": ref,
            "chg": chg,
            "chg_pct": chg_pct,
            "display": format_price_chg(price, chg_pct),
        }
    except Exception as e:
        log.warning("Yahoo %s: %s", symbol, e)
        return None


def fetch_yahoo_all() -> dict[str, Any]:
    """Map name → quote fields (price / prev / chg_pct / display)."""
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
    try:
        from app import upstox_api as ux

        return ux.enabled()
    except Exception:
        return bool(UPSTOX_ACCESS_TOKEN)


def upstox_headers() -> dict[str, str]:
    try:
        from app import upstox_api as ux

        return ux.headers()
    except Exception:
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
    # Prefer explicit previous close fields — NOT ohlc.close (that's often today)
    for key in ("previous_close", "prev_close", "close_price", "cp"):
        if q.get(key) is not None:
            try:
                val = float(q[key])
                ltp = extract_ltp(q)
                # Reject if identical to LTP (causes 0.00%)
                if ltp is not None and _nearly_eq(val, ltp):
                    continue
                return val
            except (TypeError, ValueError):
                pass
    return None


def extract_net_change_pct(q: dict | None) -> float | None:
    if not q:
        return None
    for key in ("percentage_change", "pChange", "net_change_percentage", "change_percent"):
        if q.get(key) is not None:
            try:
                return round(float(q[key]), 2)
            except (TypeError, ValueError):
                pass
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
        price = ltp or prev
        chg_pct = extract_net_change_pct(q)
        if chg_pct is None:
            chg_pct = _chg_pct(price, prev)
        # If Upstox gave 0% because prev==ltp, leave None so Yahoo can fill
        if chg_pct == 0.0 and prev is not None and price is not None and _nearly_eq(price, prev):
            chg_pct = None
            prev = None
        chg = _chg_abs(price, prev) if prev is not None else None
        out[name] = price
        out[f"{name}_ltp"] = ltp
        out[f"{name}_prev"] = prev
        out[f"{name}_chg"] = chg
        out[f"{name}_chg_pct"] = chg_pct
        out[f"{name}_display"] = format_price_chg(price, chg_pct) if chg_pct is not None else (
            f"{price:,.2f}" if price is not None else None
        )
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
