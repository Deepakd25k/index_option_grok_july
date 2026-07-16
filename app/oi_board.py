"""
Clean Call | Strike | Put OI board for Live Market.

- Left: Call OI, day Δ, LTP, prem Δ
- Center: Strike (ATM / Support green / Resistance red / MaxPain mark)
- Right: Put LTP, prem Δ, OI, day Δ
- Band: ATM ±3 (plus wall strikes if just outside)
- Readout: what OI is doing + likely next move (simple)
"""
from __future__ import annotations

import logging
from typing import Any

from app import upstox_api as ux

log = logging.getLogger(__name__)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _chg_str(n: float | None, pct: float | None = None) -> str:
    if n is None:
        return "—"
    sign = "+" if n > 0 else ""
    if abs(n) >= 100:
        s = f"{sign}{n:,.0f}"
    else:
        s = f"{sign}{n:.2f}"
    if pct is not None:
        ps = "+" if pct > 0 else ""
        s += f" ({ps}{pct:.1f}%)"
    return s


def _band_strikes(rows: list[dict], spot: float, n: int = 3) -> list[dict]:
    strikes = sorted({r["strike"] for r in rows})
    if not strikes:
        return []
    ai = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo, hi = max(0, ai - n), min(len(strikes), ai + n + 1)
    band = set(strikes[lo:hi])
    # always include top CE and PE walls if nearby (±2 steps outside)
    ce_wall = max(rows, key=lambda r: r["ce_oi"])
    pe_wall = max(rows, key=lambda r: r["pe_oi"])
    for w in (ce_wall["strike"], pe_wall["strike"]):
        if w in strikes:
            wi = strikes.index(w)
            if abs(wi - ai) <= n + 2:
                band.add(w)
    out = [r for r in rows if r["strike"] in band]
    out.sort(key=lambda r: r["strike"], reverse=True)  # high strike on top (classic)
    return out


def _readout(
    label: str,
    spot: float,
    atm: float,
    mp: float | None,
    pcr: float | None,
    ce_wall: float,
    pe_wall: float,
    tot_ce_d: float,
    tot_pe_d: float,
) -> dict[str, str]:
    """Human OI conclusion for scalp / next hour."""
    bits = []
    bias = "RANGE"
    # PCR
    if pcr is not None:
        if pcr >= 1.2:
            bits.append(f"PCR {pcr:.2f} high → put-heavy (support bias)")
        elif pcr <= 0.7:
            bits.append(f"PCR {pcr:.2f} low → call-heavy (resistance overhead)")
        else:
            bits.append(f"PCR {pcr:.2f} balanced")

    # Walls vs spot
    pe_dist = 100 * (spot - pe_wall) / spot
    ce_dist = 100 * (ce_wall - spot) / spot
    bits.append(f"Support (put wall) {pe_wall:,.0f} ({pe_dist:.1f}% below)")
    bits.append(f"Resistance (call wall) {ce_wall:,.0f} ({ce_dist:.1f}% above)")

    if mp is not None:
        mp_dist = 100 * (mp - spot) / spot
        bits.append(f"Max pain {mp:,.0f} ({mp_dist:+.1f}% from spot)")

    # Day OI flow
    if tot_pe_d > abs(tot_ce_d) and tot_pe_d > 0:
        bits.append("Day: put OI building more → dips get bought")
        bias = "SUPPORTIVE"
    elif tot_ce_d > abs(tot_pe_d) and tot_ce_d > 0:
        bits.append("Day: call OI building more → upside supply / pin risk")
        bias = "CAPPED"
    elif tot_ce_d < 0 and tot_pe_d < 0:
        bits.append("Day: both sides OI cutting → volatile / unwind")
        bias = "UNWIND"
    else:
        bits.append("Day OI mixed → trade walls, not blind trend")

    # Distance to walls → scalp plan
    if pe_dist < 0.35:
        plan = f"Near put wall — bounce long scalp toward ATM {atm:,.0f}; SL below wall. Target ~25–35 pts."
        bias = "BOUNCE_ZONE"
    elif ce_dist < 0.35:
        plan = f"Near call wall — rejection short scalp toward ATM {atm:,.0f}; SL above wall. Target ~25–35 pts."
        bias = "REJECT_ZONE"
    elif mp is not None and abs(100 * (mp - spot) / spot) > 0.6:
        plan = f"Spot far from max pain — expiry week me mean-revert toward {mp:,.0f} possible; intraday still trade OR + walls."
    else:
        plan = f"Mid-range between walls. Scalp: break of ATM zone with OI confirm, or fade into walls. Aim 25–35 pts."

    what_now = " · ".join(bits[:4])
    what_next = plan
    return {
        "bias": bias,
        "what_now": what_now,
        "what_next": what_next,
        "headline": f"{label}: {bias.replace('_', ' ')}",
    }


def build_chain_board(band: int = 3) -> dict[str, Any]:
    """
    Full payload for Live Market OI board.
    """
    if not ux.enabled():
        return {
            "ok": False,
            "error": "UPSTOX_ACCESS_TOKEN required for OI chain",
            "boards": [],
        }

    boards = []
    for label, key in (("Nifty", ux.IDX["nifty"]), ("BankNifty", ux.IDX["banknifty"])):
        chain = ux.option_chain(key, "current_week")
        spot, rows, expiry = ux.parse_chain_rows(chain)
        if not rows or spot is None:
            boards.append(
                {
                    "label": label,
                    "ok": False,
                    "error": (ux.LAST_ERROR or {}).get("body")
                    or "Chain empty — check token / expiry",
                    "rows": [],
                }
            )
            continue

        mp_data = ux.max_pain_api(key, "current_week")
        mp = None
        if isinstance(mp_data, dict):
            mp = mp_data.get("max_pain")
            expiry = expiry or str(mp_data.get("expiry_date") or "")[:10]
        if mp is None:
            mp = ux.compute_max_pain_from_rows(rows)

        walls = ux.walls_from_rows(rows, spot)
        ce_wall = walls.get("ce_wall_strike")
        pe_wall = walls.get("pe_wall_strike")
        atm = ux.atm_row(rows, spot)
        atm_strike = atm["strike"] if atm else None

        band_rows = _band_strikes(rows, spot, n=band)

        # Optional light candle Δ only for ATM CE/PE (speed) — day Δ from prev_oi always
        atm_ce_w = atm_pe_w = {}
        if atm and atm.get("ce_key"):
            try:
                atm_ce_w = ux.oi_premium_windows(atm["ce_key"])
            except Exception:
                pass
        if atm and atm.get("pe_key"):
            try:
                atm_pe_w = ux.oi_premium_windows(atm["pe_key"])
            except Exception:
                pass

        table = []
        for r in band_rows:
            strike = r["strike"]
            ce_d = r["ce_oi"] - (r.get("ce_prev_oi") or 0)
            pe_d = r["pe_oi"] - (r.get("pe_prev_oi") or 0)
            ce_dp = (
                round(100 * ce_d / r["ce_prev_oi"], 1)
                if r.get("ce_prev_oi")
                else None
            )
            pe_dp = (
                round(100 * pe_d / r["pe_prev_oi"], 1)
                if r.get("pe_prev_oi")
                else None
            )

            marks = []
            mark_class = ""
            if atm_strike is not None and abs(strike - atm_strike) < 0.01:
                marks.append("ATM")
                mark_class = "atm"
            if pe_wall is not None and abs(strike - pe_wall) < 0.01:
                marks.append("SUPPORT")
                mark_class = "support"
            if ce_wall is not None and abs(strike - ce_wall) < 0.01:
                marks.append("RESIST")
                mark_class = "resist"
            if mp is not None and abs(strike - float(mp)) < 0.01:
                marks.append("MAX PAIN")
                if mark_class == "atm":
                    mark_class = "atm maxpain"
                elif not mark_class:
                    mark_class = "maxpain"

            # 5/15/30 only on ATM rows to keep UI clean & API light
            extra = {}
            if atm_strike is not None and abs(strike - atm_strike) < 0.01:
                extra = {
                    "ce_oi_5m": _chg_str(
                        (atm_ce_w.get("oi_chg") or {}).get("5m"),
                        (atm_ce_w.get("oi_chg_pct") or {}).get("5m"),
                    ),
                    "ce_oi_15m": _chg_str(
                        (atm_ce_w.get("oi_chg") or {}).get("15m"),
                        (atm_ce_w.get("oi_chg_pct") or {}).get("15m"),
                    ),
                    "ce_oi_30m": _chg_str(
                        (atm_ce_w.get("oi_chg") or {}).get("30m"),
                        (atm_ce_w.get("oi_chg_pct") or {}).get("30m"),
                    ),
                    "pe_oi_5m": _chg_str(
                        (atm_pe_w.get("oi_chg") or {}).get("5m"),
                        (atm_pe_w.get("oi_chg_pct") or {}).get("5m"),
                    ),
                    "pe_oi_15m": _chg_str(
                        (atm_pe_w.get("oi_chg") or {}).get("15m"),
                        (atm_pe_w.get("oi_chg_pct") or {}).get("15m"),
                    ),
                    "pe_oi_30m": _chg_str(
                        (atm_pe_w.get("oi_chg") or {}).get("30m"),
                        (atm_pe_w.get("oi_chg_pct") or {}).get("30m"),
                    ),
                    "ce_prem_5m": _chg_str(
                        (atm_ce_w.get("prem_chg") or {}).get("5m"),
                        (atm_ce_w.get("prem_chg_pct") or {}).get("5m"),
                    ),
                    "pe_prem_5m": _chg_str(
                        (atm_pe_w.get("prem_chg") or {}).get("5m"),
                        (atm_pe_w.get("prem_chg_pct") or {}).get("5m"),
                    ),
                }

            table.append(
                {
                    "strike": strike,
                    "marks": marks,
                    "mark_class": mark_class,
                    "ce_oi": r["ce_oi"],
                    "ce_oi_day": _chg_str(ce_d, ce_dp),
                    "ce_ltp": r.get("ce_ltp"),
                    "pe_oi": r["pe_oi"],
                    "pe_oi_day": _chg_str(pe_d, pe_dp),
                    "pe_ltp": r.get("pe_ltp"),
                    **extra,
                }
            )

        tot_ce = sum(r["ce_oi"] for r in rows)
        tot_pe = sum(r["pe_oi"] for r in rows)
        prev_ce = sum(r.get("ce_prev_oi") or 0 for r in rows)
        prev_pe = sum(r.get("pe_prev_oi") or 0 for r in rows)
        pcr = (tot_pe / tot_ce) if tot_ce else None
        tot_ce_d = tot_ce - prev_ce
        tot_pe_d = tot_pe - prev_pe

        read = _readout(
            label,
            spot,
            atm_strike or spot,
            float(mp) if mp is not None else None,
            pcr,
            float(ce_wall or spot),
            float(pe_wall or spot),
            tot_ce_d,
            tot_pe_d,
        )

        boards.append(
            {
                "label": label,
                "ok": True,
                "spot": spot,
                "expiry": expiry,
                "atm": atm_strike,
                "max_pain": mp,
                "pcr": round(pcr, 3) if pcr is not None else None,
                "ce_wall": ce_wall,
                "pe_wall": pe_wall,
                "tot_ce_oi": tot_ce,
                "tot_pe_oi": tot_pe,
                "tot_ce_day": _chg_str(tot_ce_d),
                "tot_pe_day": _chg_str(tot_pe_d),
                "read": read,
                "rows": table,
            }
        )

    return {"ok": True, "boards": boards, "source": "upstox"}
