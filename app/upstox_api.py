"""
Central Upstox client — option chain, max pain, contracts, futures, candles.

Docs:
  GET /v2/option/chain?instrument_key=&expiry_date=   (or current_week)
  GET /v2/option/contract?instrument_key=
  GET /v2/market/max-pain?instrument_key=&expiry=&date=&bucket_interval=
  GET /v2/market/oi?instrument_key=&expiry=&date=
  GET /v2/historical-candle/{key}/{interval}/{to}/{from}
  GET /v2/historical-candle/intraday/{key}/{interval}
  GET /v2/market-quote/quotes?instrument_key=
  Instruments: https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from app.config import UPSTOX_ACCESS_TOKEN, UPSTOX_BASE

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")

# Underlying keys
IDX = {
    "nifty": "NSE_INDEX|Nifty 50",
    "banknifty": "NSE_INDEX|Nifty Bank",
    "sensex": "BSE_INDEX|SENSEX",
    "vix": "NSE_INDEX|India VIX",
}

_FO_CACHE: dict[str, Any] = {"ts": 0.0, "rows": []}


def enabled() -> bool:
    return bool(UPSTOX_ACCESS_TOKEN)


def headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    }


def _get(path: str, params: dict | None = None, timeout: int = 25) -> dict | list | None:
    if not enabled():
        return None
    url = path if path.startswith("http") else f"{UPSTOX_BASE}{path}"
    try:
        r = requests.get(url, headers=headers(), params=params or {}, timeout=timeout)
        if r.status_code != 200:
            log.warning("Upstox %s → %s %s", path, r.status_code, r.text[:220])
            return None
        body = r.json()
        if isinstance(body, dict) and body.get("status") == "error":
            log.warning("Upstox error %s %s", path, body)
            return None
        return body
    except Exception as e:
        log.warning("Upstox %s: %s", path, e)
        return None


# ── Quotes (live Nifty / BN / Sensex) ────────────────────────
def quotes(instrument_keys: list[str]) -> dict[str, dict]:
    if not instrument_keys or not enabled():
        return {}
    body = _get("/market-quote/quotes", {"instrument_key": ",".join(instrument_keys)})
    if not body or not isinstance(body, dict):
        return {}
    data = body.get("data") or {}
    out: dict[str, dict] = {}
    for k, v in data.items():
        out[k] = v
        out[k.replace(":", "|")] = v
    return out


def index_ltp_map() -> dict[str, float | None]:
    """nifty/banknifty/sensex/vix last prices from Upstox."""
    rich = live_index_bundle()
    return {k: (v or {}).get("price") for k, v in rich.get("indices", {}).items()}


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_quote(q: dict | None) -> dict[str, Any] | None:
    """Normalize Upstox full market quote → price, prev, chg, chg_pct, ohlc."""
    if not q or not isinstance(q, dict):
        return None
    ohlc = q.get("ohlc") if isinstance(q.get("ohlc"), dict) else {}
    price = _f(q.get("last_price") if q.get("last_price") is not None else q.get("ltp"))
    if price is None:
        price = _f(ohlc.get("close"))
    # Prefer true previous close fields (not today's ohlc.close)
    prev = None
    for key in ("previous_close", "prev_close", "close_price", "cp"):
        prev = _f(q.get(key))
        if prev is not None and price is not None and abs(prev - price) > 1e-6:
            break
        if prev is not None and price is None:
            break
        prev = None
    # net change from API
    net = _f(q.get("net_change"))
    chg_pct = None
    for key in ("percentage_change", "pChange", "net_change_percentage", "change_percent"):
        chg_pct = _f(q.get(key))
        if chg_pct is not None:
            break
    if chg_pct is None and price is not None and prev not in (None, 0):
        chg_pct = round(100.0 * (price - prev) / prev, 2)
    elif chg_pct is None and price is not None and net is not None and price - net != 0:
        prev_calc = price - net
        if prev_calc:
            chg_pct = round(100.0 * net / prev_calc, 2)
            prev = prev or prev_calc
    if net is None and price is not None and prev is not None:
        net = round(price - prev, 4)
    # display
    if price is None:
        return None
    sign = "+" if (chg_pct or 0) > 0 else ""
    disp = f"{price:,.2f}"
    if chg_pct is not None:
        disp = f"{price:,.2f} ({sign}{chg_pct:.2f}%)"
    return {
        "price": price,
        "prev": prev,
        "chg": net,
        "chg_pct": chg_pct,
        "display": disp,
        "open": _f(ohlc.get("open")),
        "high": _f(ohlc.get("high")),
        "low": _f(ohlc.get("low")),
        "close": _f(ohlc.get("close")),
        "volume": _f(q.get("volume")),
        "source": "upstox",
    }


def live_index_bundle(include_futures: bool = False) -> dict[str, Any]:
    """
    Live bundle for continuous UI poll — **Upstox only** (fast).

    Always: Nifty, BankNifty, Sensex, VIX, GIFT.
    Optional: near index futures LTP (slower first time — instruments download).
    """
    if not enabled():
        return {
            "ok": False,
            "source": "none",
            "error": "UPSTOX_ACCESS_TOKEN not set",
            "indices": {},
            "futures": {},
        }

    keys = [
        IDX["nifty"],
        IDX["banknifty"],
        IDX["sensex"],
        IDX["vix"],
        "GLOBAL_INDEX|SGX NIFTY",
    ]
    raw = quotes(keys)
    name_map = {
        "nifty": IDX["nifty"],
        "banknifty": IDX["banknifty"],
        "sensex": IDX["sensex"],
        "vix": IDX["vix"],
        "gift": "GLOBAL_INDEX|SGX NIFTY",
    }
    indices: dict[str, Any] = {}
    for name, ik in name_map.items():
        q = raw.get(ik) or raw.get(ik.replace("|", ":"))
        parsed = _parse_quote(q)
        if parsed:
            indices[name] = parsed

    futures: dict[str, Any] = {}
    if include_futures:
        try:
            for label, search in (("nifty_fut", "NIFTY"), ("banknifty_fut", "BANKNIFTY")):
                fut = nearest_index_future(search)
                if not fut or not fut.get("instrument_key"):
                    continue
                ik = fut["instrument_key"]
                fq = quotes([ik])
                q = fq.get(ik) or fq.get(str(ik).replace("|", ":"))
                parsed = _parse_quote(q)
                if parsed:
                    parsed["instrument_key"] = ik
                    parsed["trading_symbol"] = fut.get("trading_symbol")
                    parsed["expiry"] = str(fut.get("expiry") or "")[:10]
                    futures[label] = parsed
        except Exception as e:
            log.warning("live futures: %s", e)

    return {
        "ok": bool(indices),
        "source": "upstox",
        "indices": indices,
        "futures": futures,
        "ts": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S IST"),
    }


# ── Option contracts / chain / max pain / OI ─────────────────
def option_contracts(instrument_key: str) -> list[dict]:
    body = _get("/option/contract", {"instrument_key": instrument_key})
    if not body or not isinstance(body, dict):
        return []
    return list(body.get("data") or [])


def nearest_expiry(instrument_key: str) -> str | None:
    """Nearest upcoming expiry YYYY-MM-DD from option contracts."""
    contracts = option_contracts(instrument_key)
    today = datetime.now(TZ).date()
    exps: set[str] = set()
    for c in contracts:
        e = c.get("expiry")
        if not e:
            continue
        exps.add(str(e)[:10])
    future = []
    for e in sorted(exps):
        try:
            ed = date.fromisoformat(e)
        except ValueError:
            continue
        if ed >= today:
            future.append(e)
    return future[0] if future else (sorted(exps)[0] if exps else None)


def option_chain(instrument_key: str, expiry: str | None = None) -> list[dict]:
    """
    Put/call chain. expiry can be YYYY-MM-DD or keyword current_week.
    """
    exp = expiry or "current_week"
    body = _get(
        "/option/chain",
        {"instrument_key": instrument_key, "expiry_date": exp},
    )
    if not body or not isinstance(body, dict):
        # fallback: resolve real expiry date
        if exp == "current_week":
            real = nearest_expiry(instrument_key)
            if real:
                body = _get(
                    "/option/chain",
                    {"instrument_key": instrument_key, "expiry_date": real},
                )
    if not body or not isinstance(body, dict):
        return []
    return list(body.get("data") or [])


def parse_chain_rows(chain: list[dict]) -> tuple[float | None, list[dict], str | None]:
    """spot, rows with OI/premium/instrument keys, expiry"""
    spot = None
    expiry = None
    rows: list[dict] = []
    for item in chain:
        if item.get("underlying_spot_price") is not None:
            try:
                spot = float(item["underlying_spot_price"])
            except (TypeError, ValueError):
                pass
        if item.get("expiry"):
            expiry = str(item["expiry"])[:10]
        strike = item.get("strike_price")
        if strike is None:
            continue
        ce = item.get("call_options") or {}
        pe = item.get("put_options") or {}
        ce_md = ce.get("market_data") or ce
        pe_md = pe.get("market_data") or pe
        rows.append(
            {
                "strike": float(strike),
                "ce_oi": float(ce_md.get("oi") or 0),
                "pe_oi": float(pe_md.get("oi") or 0),
                "ce_vol": float(ce_md.get("volume") or 0),
                "pe_vol": float(pe_md.get("volume") or 0),
                "ce_prev_oi": float(ce_md.get("prev_oi") or 0),
                "pe_prev_oi": float(pe_md.get("prev_oi") or 0),
                "ce_ltp": _f(ce_md.get("ltp")),
                "pe_ltp": _f(pe_md.get("ltp")),
                "ce_key": ce.get("instrument_key"),
                "pe_key": pe.get("instrument_key"),
                "row_pcr": item.get("pcr"),
            }
        )
    return spot, rows, expiry


def atm_row(rows: list[dict], spot: float | None) -> dict | None:
    if not rows or spot is None:
        return None
    return min(rows, key=lambda r: abs(r["strike"] - spot))


def intraday_v3(instrument_key: str, unit: str = "minutes", interval: str = "1") -> list:
    """
    GET /v3/historical-candle/intraday/{key}/{unit}/{interval}
    Candle: [ts, o, h, l, c, volume, oi]
    """
    if not enabled() or not instrument_key:
        return []
    path = (
        f"https://api.upstox.com/v3/historical-candle/intraday/"
        f"{quote(instrument_key, safe='')}/{unit}/{interval}"
    )
    body = _get(path, timeout=30)
    if not body or not isinstance(body, dict):
        return []
    return list((body.get("data") or {}).get("candles") or [])


def _parse_ts(ts: Any) -> datetime | None:
    if ts is None:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def candle_snapshot(candles: list, minutes_ago: int | None = None, day_open: bool = False) -> dict | None:
    """
    Pick a candle for 'now', N minutes ago, or first bar of the day (≈9:15).
    Candles may be newest-first or oldest-first — we sort ascending by time.
    Returns {ts, close, oi, volume}.
    """
    parsed: list[tuple[datetime, list]] = []
    for c in candles:
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        dt = _parse_ts(c[0])
        if not dt:
            continue
        parsed.append((dt, list(c)))
    if not parsed:
        return None
    parsed.sort(key=lambda x: x[0])
    now = datetime.now(TZ)

    def pack(dt: datetime, c: list) -> dict:
        oi = float(c[6]) if len(c) > 6 and c[6] is not None else None
        vol = float(c[5]) if len(c) > 5 and c[5] is not None else None
        return {
            "ts": dt.strftime("%H:%M"),
            "close": float(c[4]),
            "oi": oi,
            "volume": vol,
        }

    if day_open:
        # first candle at/after 09:15 today
        today = now.date()
        for dt, c in parsed:
            if dt.date() == today and (dt.hour > 9 or (dt.hour == 9 and dt.minute >= 15)):
                return pack(dt, c)
        # fallback first of day
        for dt, c in parsed:
            if dt.date() == today:
                return pack(dt, c)
        return pack(parsed[0][0], parsed[0][1])

    if minutes_ago is None or minutes_ago <= 0:
        return pack(parsed[-1][0], parsed[-1][1])

    target = now - timedelta(minutes=minutes_ago)
    # last candle at or before target
    chosen = parsed[0]
    for dt, c in parsed:
        if dt <= target:
            chosen = (dt, c)
        else:
            break
    return pack(chosen[0], chosen[1])


def oi_premium_windows(instrument_key: str) -> dict[str, Any]:
    """
    ATM CE/PE style windows from 1-min candles:
    now, 5m, 15m, 30m, day_open → OI + premium (close).
    """
    candles = intraday_v3(instrument_key, "minutes", "1")
    if not candles:
        # try 5-min if 1-min empty
        candles = intraday_v3(instrument_key, "minutes", "5")
    now = candle_snapshot(candles, 0)
    w5 = candle_snapshot(candles, 5)
    w15 = candle_snapshot(candles, 15)
    w30 = candle_snapshot(candles, 30)
    wopen = candle_snapshot(candles, day_open=True)

    def delta(cur: dict | None, old: dict | None, field: str) -> float | None:
        if not cur or not old:
            return None
        a, b = cur.get(field), old.get(field)
        if a is None or b is None:
            return None
        return float(a) - float(b)

    def pct(cur: dict | None, old: dict | None, field: str) -> float | None:
        if not cur or not old:
            return None
        a, b = cur.get(field), old.get(field)
        if a is None or b in (None, 0):
            return None
        return round(100.0 * (float(a) - float(b)) / float(b), 2)

    return {
        "now": now,
        "m5": w5,
        "m15": w15,
        "m30": w30,
        "day_open": wopen,
        "oi_chg": {
            "5m": delta(now, w5, "oi"),
            "15m": delta(now, w15, "oi"),
            "30m": delta(now, w30, "oi"),
            "day": delta(now, wopen, "oi"),
        },
        "oi_chg_pct": {
            "5m": pct(now, w5, "oi"),
            "15m": pct(now, w15, "oi"),
            "30m": pct(now, w30, "oi"),
            "day": pct(now, wopen, "oi"),
        },
        "prem_chg": {
            "5m": delta(now, w5, "close"),
            "15m": delta(now, w15, "close"),
            "30m": delta(now, w30, "close"),
            "day": delta(now, wopen, "close"),
        },
        "prem_chg_pct": {
            "5m": pct(now, w5, "close"),
            "15m": pct(now, w15, "close"),
            "30m": pct(now, w30, "close"),
            "day": pct(now, wopen, "close"),
        },
    }


def max_pain_api(instrument_key: str, expiry: str = "current_week") -> dict | None:
    """Native Upstox max-pain endpoint."""
    today = datetime.now(TZ).date().isoformat()
    body = _get(
        "/market/max-pain",
        {
            "instrument_key": instrument_key,
            "expiry": expiry,
            "date": today,
            "bucket_interval": 60,
        },
    )
    if not body or not isinstance(body, dict):
        # try resolved expiry
        real = nearest_expiry(instrument_key)
        if real and real != expiry:
            body = _get(
                "/market/max-pain",
                {
                    "instrument_key": instrument_key,
                    "expiry": real,
                    "date": today,
                    "bucket_interval": 60,
                },
            )
    if not body or not isinstance(body, dict):
        return None
    return body.get("data")


def market_oi(instrument_key: str, expiry: str = "current_week") -> dict | None:
    today = datetime.now(TZ).date().isoformat()
    body = _get(
        "/market/oi",
        {"instrument_key": instrument_key, "expiry": expiry, "date": today},
    )
    if not body or not isinstance(body, dict):
        real = nearest_expiry(instrument_key)
        if real:
            body = _get(
                "/market/oi",
                {"instrument_key": instrument_key, "expiry": real, "date": today},
            )
    if not body or not isinstance(body, dict):
        return None
    return body.get("data")


def compute_max_pain_from_rows(rows: list[dict]) -> float | None:
    if not rows:
        return None
    strikes = sorted({r["strike"] for r in rows})
    best_x, best_pain = None, None
    for x in strikes:
        pain = 0.0
        for r in rows:
            k = r["strike"]
            pain += r["ce_oi"] * max(0.0, x - k)
            pain += r["pe_oi"] * max(0.0, k - x)
        if best_pain is None or pain < best_pain:
            best_pain, best_x = pain, x
    return best_x


def walls_from_rows(rows: list[dict], spot: float | None) -> dict[str, Any]:
    if not rows:
        return {}
    ce_wall = max(rows, key=lambda r: r["ce_oi"])
    pe_wall = max(rows, key=lambda r: r["pe_oi"])
    tot_ce = sum(r["ce_oi"] for r in rows) or 0
    tot_pe = sum(r["pe_oi"] for r in rows) or 0
    pcr = (tot_pe / tot_ce) if tot_ce else None
    return {
        "ce_wall_strike": ce_wall["strike"],
        "ce_wall_oi": ce_wall["ce_oi"],
        "pe_wall_strike": pe_wall["strike"],
        "pe_wall_oi": pe_wall["pe_oi"],
        "pcr": round(pcr, 3) if pcr is not None else None,
        "spot": spot,
        "dist_ce_pct": round(100 * (ce_wall["strike"] - spot) / spot, 2) if spot else None,
        "dist_pe_pct": round(100 * (pe_wall["strike"] - spot) / spot, 2) if spot else None,
    }


# ── Futures instrument resolution ────────────────────────────
def _load_fo_instruments() -> list[dict]:
    import time

    now = time.time()
    if _FO_CACHE["rows"] and now - _FO_CACHE["ts"] < 3600 * 6:
        return _FO_CACHE["rows"]
    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    # complete file is huge; try NSE FO segment file if exists
    urls = [
        "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
        "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",
    ]
    rows: list[dict] = []
    for u in urls:
        try:
            r = requests.get(u, timeout=60, headers={"User-Agent": "PremarketDashboard/1.0"})
            if r.status_code != 200:
                continue
            raw = r.content
            if u.endswith(".gz"):
                raw = gzip.decompress(raw)
            data = json.loads(raw)
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("data") or list(data.values())
            if rows:
                break
        except Exception as e:
            log.warning("FO instruments %s: %s", u, e)
    # keep only index futures
    fut = [
        x
        for x in rows
        if isinstance(x, dict)
        and x.get("instrument_type") in ("FUTIDX", "FUTSTK", "FUT")
        and str(x.get("segment", "")).endswith("FO")
    ]
    # if filter empty, keep FUTIDX name match later on full rows
    use = fut if fut else [x for x in rows if isinstance(x, dict)]
    _FO_CACHE["rows"] = use
    _FO_CACHE["ts"] = now
    return use


def nearest_index_future(name: str) -> dict | None:
    """
    name: NIFTY | BANKNIFTY | SENSEX
    Returns instrument dict with instrument_key for nearest expiry FUTIDX.
    """
    name_u = name.upper().replace(" ", "")
    aliases = {
        "NIFTY": ("NIFTY", "NIFTY 50"),
        "BANKNIFTY": ("BANKNIFTY", "NIFTY BANK"),
        "SENSEX": ("SENSEX",),
    }
    keys = aliases.get(name_u, (name_u,))
    rows = _load_fo_instruments()
    today = datetime.now(TZ).date()
    candidates: list[tuple[date, dict]] = []
    for x in rows:
        n = str(x.get("name") or x.get("trading_symbol") or "").upper().replace(" ", "")
        itype = str(x.get("instrument_type") or "")
        if "FUT" not in itype.upper() and itype not in ("FUTIDX",):
            # trading symbol ends with FUT
            ts = str(x.get("trading_symbol") or "")
            if not ts.upper().endswith("FUT"):
                continue
        matched = any(a.replace(" ", "") in n or n.startswith(a.replace(" ", "")) for a in keys)
        if not matched:
            # BANKNIFTY in trading_symbol
            ts = str(x.get("trading_symbol") or "").upper()
            matched = any(a in ts for a in keys)
        if not matched:
            continue
        exp = x.get("expiry")
        if not exp:
            continue
        try:
            ed = date.fromisoformat(str(exp)[:10])
        except ValueError:
            continue
        if ed < today:
            continue
        candidates.append((ed, x))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


# ── Candles ──────────────────────────────────────────────────
def historical_day(instrument_key: str, days: int = 25) -> list:
    to_d = datetime.now(TZ).date()
    from_d = to_d - timedelta(days=days)
    path = (
        f"/historical-candle/{quote(instrument_key, safe='')}/day/"
        f"{to_d.isoformat()}/{from_d.isoformat()}"
    )
    body = _get(path, timeout=30)
    if not body or not isinstance(body, dict):
        return []
    return list((body.get("data") or {}).get("candles") or [])


def intraday(instrument_key: str, interval: str = "30minute") -> list:
    path = f"/historical-candle/intraday/{quote(instrument_key, safe='')}/{interval}"
    body = _get(path, timeout=30)
    if not body or not isinstance(body, dict):
        # v3 style
        body = _get(
            f"https://api.upstox.com/v3/historical-candle/intraday/"
            f"{quote(instrument_key, safe='')}/minutes/30",
            timeout=30,
        )
    if not body or not isinstance(body, dict):
        return []
    return list((body.get("data") or {}).get("candles") or [])
