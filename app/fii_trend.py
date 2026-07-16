"""FII-only OI week trend + next-day match score.

Logic (simple, transparent):
  Day T OI report (after close ~7:30 PM) → signal for Day T+1 session.
  Signal BULLISH if FII Index Fut Net (Long − Short) > 0
  Signal BEARISH if Net < 0
  Next-day return = (Nifty close T+1 − Nifty close T) / Nifty close T
  MATCH if signal direction == next-day return sign
  NEUTRAL next day (|ret| < 0.05%) counts as partial (skipped from hit-rate denom)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from app.nse_oi import download_oi_for_date, enrich_participant, parse_participant_csv

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")
UA = {"User-Agent": "PremarketDashboard/1.1", "Accept": "application/json"}

NEUTRAL_BAND = 0.0005  # 0.05% — too small to score


def _trading_days_back(n: int = 12) -> list[date]:
    """Last n calendar weekdays including today (may not all have OI yet)."""
    out: list[date] = []
    d = datetime.now(TZ).date()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def fetch_fii_oi_series(lookback_sessions: int = 10) -> list[dict[str, Any]]:
    """Newest-first list of FII-only OI daily rows for ~1 week+."""
    rows: list[dict[str, Any]] = []
    for d in _trading_days_back(lookback_sessions + 4):
        if len(rows) >= lookback_sessions:
            break
        got = download_oi_for_date(d)
        if not got:
            continue
        text, ymd = got
        try:
            raw = parse_participant_csv(text)
            if "FII" not in raw:
                continue
            f = enrich_participant(raw["FII"])
        except Exception as e:
            log.warning("FII parse %s: %s", ymd, e)
            continue
        rows.append(
            {
                "oi_date": ymd,
                "fii_idx_fut_long": f.get("idx_fut_long"),
                "fii_idx_fut_short": f.get("idx_fut_short"),
                "fii_idx_fut_long_pct": f.get("idx_fut_long_pct"),
                "fii_idx_fut_short_pct": f.get("idx_fut_short_pct"),
                "fii_idx_fut_long_display": f.get("idx_fut_long_display"),
                "fii_idx_fut_short_display": f.get("idx_fut_short_display"),
                "fii_idx_fut_net": f.get("idx_fut_net"),
                "fii_idx_fut_ratio": f.get("idx_fut_ratio"),
                "fii_idx_opt_pcr_short": f.get("idx_opt_pcr_short"),
            }
        )
    # newest first already from walking back
    return rows


def fetch_nifty_closes(days: int = 20) -> dict[str, float]:
    """Map yyyy-mm-dd → Nifty daily close via Yahoo."""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote('^NSEI', safe='')}?interval=1d&range=1mo"
    )
    try:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200:
            return {}
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            return {}
        ts = result[0].get("timestamp") or []
        closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out: dict[str, float] = {}
        for t, c in zip(ts, closes):
            if c is None:
                continue
            # Yahoo timestamps are exchange local for NSE often; use IST date
            ymd = datetime.fromtimestamp(t, tz=TZ).date().isoformat()
            out[ymd] = float(c)
        return out
    except Exception as e:
        log.warning("nifty closes: %s", e)
        return {}


def signal_from_net(net: float | None) -> str:
    if net is None:
        return "UNKNOWN"
    if net > 0:
        return "BULLISH"  # net long
    if net < 0:
        return "BEARISH"  # net short
    return "NEUTRAL"


def build_week_trend(lookback: int = 8) -> dict[str, Any]:
    """
    Build last ~1 week FII OI trend + next-day match stats.
    OI of day T is published evening of T → applies to session T+1.
    """
    series = fetch_fii_oi_series(lookback_sessions=lookback)
    nifty = fetch_nifty_closes()

    # chronological oldest → newest for deltas
    chrono = list(reversed(series))
    enriched: list[dict[str, Any]] = []

    for i, row in enumerate(chrono):
        ymd = row["oi_date"]
        net = row.get("fii_idx_fut_net")
        long_v = row.get("fii_idx_fut_long")
        short_v = row.get("fii_idx_fut_short")
        prev = chrono[i - 1] if i > 0 else None

        d_long = (long_v - prev["fii_idx_fut_long"]) if prev and long_v is not None and prev.get("fii_idx_fut_long") is not None else None
        d_short = (short_v - prev["fii_idx_fut_short"]) if prev and short_v is not None and prev.get("fii_idx_fut_short") is not None else None
        d_net = (net - prev["fii_idx_fut_net"]) if prev and net is not None and prev.get("fii_idx_fut_net") is not None else None

        # Flow signal: if FII added short / reduced net → BEARISH; covered short / raised net → BULLISH
        if d_net is not None:
            if d_net > 0:
                flow = "COVERING / BULLISH"  # net improved (less short or more long)
            elif d_net < 0:
                flow = "ADDING SHORT / BEARISH"
            else:
                flow = "FLAT"
        else:
            flow = "—"

        bias = signal_from_net(net)

        # Next trading day nifty move (after this OI date)
        next_ymd = _next_key_in_map(ymd, nifty)
        nifty_t = nifty.get(ymd)
        nifty_next = nifty.get(next_ymd) if next_ymd else None
        next_ret = None
        next_dir = None
        if nifty_t and nifty_next and nifty_t != 0:
            next_ret = (nifty_next - nifty_t) / nifty_t
            if abs(next_ret) < NEUTRAL_BAND:
                next_dir = "FLAT"
            elif next_ret > 0:
                next_dir = "UP"
            else:
                next_dir = "DOWN"

        # Match: OI bias for next day vs actual next day move
        # BEARISH expects DOWN, BULLISH expects UP
        match = None
        match_label = "—"
        if next_dir in ("UP", "DOWN") and bias in ("BULLISH", "BEARISH"):
            expected = "UP" if bias == "BULLISH" else "DOWN"
            match = expected == next_dir
            match_label = "MATCH ✅" if match else "MISS ❌"
        elif next_dir == "FLAT":
            match_label = "FLAT (skip)"
        elif next_dir is None:
            match_label = "pending / no next day"

        # Flow match (often better): day-over-day OI change vs next day
        flow_match = None
        flow_match_label = "—"
        if d_net is not None and next_dir in ("UP", "DOWN"):
            # d_net > 0 (covering) expect UP; d_net < 0 expect DOWN
            exp = "UP" if d_net > 0 else "DOWN" if d_net < 0 else None
            if exp:
                flow_match = exp == next_dir
                flow_match_label = "MATCH ✅" if flow_match else "MISS ❌"

        enriched.append(
            {
                **row,
                "delta_long": d_long,
                "delta_short": d_short,
                "delta_net": d_net,
                "bias_signal": bias,
                "flow_signal": flow,
                "nifty_close": nifty_t,
                "next_session": next_ymd,
                "next_nifty_close": nifty_next,
                "next_day_return_pct": round(next_ret * 100, 3) if next_ret is not None else None,
                "next_day_dir": next_dir,
                "bias_match": match,
                "bias_match_label": match_label,
                "flow_match": flow_match,
                "flow_match_label": flow_match_label,
            }
        )

    # newest first for UI
    enriched_desc = list(reversed(enriched))

    # Accuracy only on scored rows (have next day)
    bias_scored = [r for r in enriched if r.get("bias_match") is not None]
    flow_scored = [r for r in enriched if r.get("flow_match") is not None]
    bias_hits = sum(1 for r in bias_scored if r["bias_match"])
    flow_hits = sum(1 for r in flow_scored if r["flow_match"])

    bias_acc = round(100 * bias_hits / len(bias_scored), 1) if bias_scored else None
    flow_acc = round(100 * flow_hits / len(flow_scored), 1) if flow_scored else None

    # Week slice for display (last 5–7 sessions with OI)
    week = enriched_desc[:7]

    return {
        "sessions": week,
        "sessions_all": enriched_desc,
        "summary": {
            "sessions_with_oi": len(week),
            "bias_hits": bias_hits,
            "bias_total": len(bias_scored),
            "bias_accuracy_pct": bias_acc,
            "flow_hits": flow_hits,
            "flow_total": len(flow_scored),
            "flow_accuracy_pct": flow_acc,
            "explain": (
                "Bias: OI Net (L−S) > 0 → BULLISH next day; < 0 → BEARISH. "
                "Flow: ΔNet day-over-day > 0 (covering) → BULLISH next day; < 0 (more short) → BEARISH. "
                "Match = next day Nifty close direction agrees."
            ),
            "note": "OI of date T (evening file) is scored against Nifty move on the next session after T.",
        },
    }


def _next_key_in_map(ymd: str, m: dict[str, float]) -> str | None:
    """Next date key in map after ymd (sorted)."""
    keys = sorted(m.keys())
    for k in keys:
        if k > ymd:
            return k
    return None
