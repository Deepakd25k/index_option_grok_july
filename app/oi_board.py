"""
Live Market OI board — Call | Strike | Put

User ask:
  ATM (e.g. 24100) ± 3 strikes
  For each CE & PE show actual OI & premium at:
    now · 5 min ago · 15 min ago · 30 min ago · day open (~9:15)
  plus Δ (inc/dec) vs those points
  Strike marks: ATM / SUPPORT(green) / RESIST(red) / MAX PAIN
  Simple readout: kya ho raha hai / aage kya

Data: Upstox option/chain (live OI+LTP) + v3 1-min candles (history of OI+close)
"""
from __future__ import annotations

import logging
from typing import Any

from app import upstox_api as ux

log = logging.getLogger(__name__)


def _chg_str(n: float | None, pct: float | None = None) -> str:
    if n is None:
        return "—"
    sign = "+" if n > 0 else ""
    if abs(n) >= 50:
        s = f"{sign}{n:,.0f}"
    else:
        s = f"{sign}{n:.2f}"
    if pct is not None:
        ps = "+" if pct > 0 else ""
        s += f" ({ps}{pct:.1f}%)"
    return s


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return round(100.0 * (a - b) / b, 1)


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def _snap_vals(w: dict | None, key: str) -> dict[str, float | None]:
    """Extract absolute oi/close at now, 5m, 15m, 30m, day_open from oi_premium_windows()."""
    w = w or {}
    out = {}
    for name, sk in (
        ("now", "now"),
        ("m5", "m5"),
        ("m15", "m15"),
        ("m30", "m30"),
        ("open", "day_open"),
    ):
        snap = w.get(sk) or {}
        out[name] = snap.get(key)
    return out


def _band_rows(rows: list[dict], spot: float, n: int = 3) -> list[dict]:
    strikes = sorted({r["strike"] for r in rows})
    if not strikes:
        return []
    ai = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo, hi = max(0, ai - n), min(len(strikes), ai + n + 1)
    band = set(strikes[lo:hi])
    # include walls if close
    ce_wall = max(rows, key=lambda r: r["ce_oi"])["strike"]
    pe_wall = max(rows, key=lambda r: r["pe_oi"])["strike"]
    for w in (ce_wall, pe_wall):
        if w in strikes and abs(strikes.index(w) - ai) <= n + 2:
            band.add(w)
    out = [r for r in rows if r["strike"] in band]
    out.sort(key=lambda r: r["strike"], reverse=True)
    return out


def _side_block(live_oi, live_ltp, windows: dict, field_oi="oi", field_px="close") -> dict:
    """Absolute levels + changes for one side (CE or PE)."""
    abs_oi = _snap_vals(windows, field_oi)
    abs_px = _snap_vals(windows, field_px)
    # prefer live chain for "now"
    oi_now = abs_oi.get("now") if abs_oi.get("now") is not None else live_oi
    px_now = abs_px.get("now") if abs_px.get("now") is not None else live_ltp

    def pack(level_now, levels, label):
        old = levels.get(label)
        d = _delta(level_now, old)
        p = _pct(level_now, old)
        return {
            "at": old,
            "chg": d,
            "chg_pct": p,
            "disp": _chg_str(d, p) if d is not None else "—",
            "at_disp": f"{old:,.0f}" if old is not None and field_oi == "oi" else (
                f"{old:.2f}" if old is not None else "—"
            ),
        }

    # for premium use 2 decimals in at_disp
    def pack_px(level_now, levels, label):
        old = levels.get(label)
        d = _delta(level_now, old)
        p = _pct(level_now, old)
        return {
            "at": old,
            "chg": d,
            "chg_pct": p,
            "disp": _chg_str(d, p) if d is not None else "—",
            "at_disp": f"{old:.2f}" if old is not None else "—",
        }

    oi_now_f = float(oi_now) if oi_now is not None else None
    px_now_f = float(px_now) if px_now is not None else None

    return {
        "oi_now": oi_now_f,
        "oi_now_disp": f"{oi_now_f:,.0f}" if oi_now_f is not None else "—",
        "prem_now": px_now_f,
        "prem_now_disp": f"{px_now_f:.2f}" if px_now_f is not None else "—",
        "oi_5m": pack(oi_now_f, abs_oi, "m5"),
        "oi_15m": pack(oi_now_f, abs_oi, "m15"),
        "oi_30m": pack(oi_now_f, abs_oi, "m30"),
        "oi_open": pack(oi_now_f, abs_oi, "open"),
        "prem_5m": pack_px(px_now_f, abs_px, "m5"),
        "prem_15m": pack_px(px_now_f, abs_px, "m15"),
        "prem_30m": pack_px(px_now_f, abs_px, "m30"),
        "prem_open": pack_px(px_now_f, abs_px, "open"),
        # absolute at times (what user asked: 1:25 pe kya tha)
        "oi_at_5m": abs_oi.get("m5"),
        "oi_at_15m": abs_oi.get("m15"),
        "oi_at_30m": abs_oi.get("m30"),
        "oi_at_open": abs_oi.get("open"),
        "prem_at_5m": abs_px.get("m5"),
        "prem_at_15m": abs_px.get("m15"),
        "prem_at_30m": abs_px.get("m30"),
        "prem_at_open": abs_px.get("open"),
        "ts_5m": (windows or {}).get("m5", {}).get("ts"),
        "ts_15m": (windows or {}).get("m15", {}).get("ts"),
        "ts_30m": (windows or {}).get("m30", {}).get("ts"),
        "ts_open": (windows or {}).get("day_open", {}).get("ts"),
        "ts_now": (windows or {}).get("now", {}).get("ts"),
    }


def _readout(label, spot, atm, mp, pcr, ce_wall, pe_wall, tot_ce_d, tot_pe_d) -> dict:
    bits = []
    bias = "RANGE"
    if pcr is not None:
        if pcr >= 1.2:
            bits.append(f"PCR {pcr:.2f} put-heavy (support bias)")
        elif pcr <= 0.7:
            bits.append(f"PCR {pcr:.2f} call-heavy (supply up)")
        else:
            bits.append(f"PCR {pcr:.2f} balanced")

    pe_dist = 100 * (spot - pe_wall) / spot if pe_wall else 99
    ce_dist = 100 * (ce_wall - spot) / spot if ce_wall else 99
    bits.append(f"Support {pe_wall:,.0f}" if pe_wall else "")
    bits.append(f"Resist {ce_wall:,.0f}" if ce_wall else "")
    if mp is not None:
        bits.append(f"Max pain {float(mp):,.0f}")

    if pe_dist < 0.35:
        bias = "BOUNCE"
        plan = f"Near put wall — long scalp to ATM {atm:,.0f}, target +25–35, SL below wall."
    elif ce_dist < 0.35:
        bias = "REJECT"
        plan = f"Near call wall — short scalp to ATM {atm:,.0f}, target −25–35, SL above wall."
    elif tot_pe_d > 0 and tot_pe_d > abs(tot_ce_d):
        bias = "SUPPORTIVE"
        plan = "Put OI building — buy dips near support; avoid panic shorts."
    elif tot_ce_d > 0 and tot_ce_d > abs(tot_pe_d):
        bias = "CAPPED"
        plan = "Call OI building — sell rips into resistance; trail longs tight."
    else:
        plan = f"Mid walls. Scalp OR break or fade into S/R. Aim 25–35 pts around ATM {atm:,.0f}."

    return {
        "bias": bias,
        "headline": f"{label}: {bias}",
        "what_now": " · ".join([x for x in bits if x])[:220],
        "what_next": plan,
    }


def build_chain_board(band: int = 3, with_windows: bool = True) -> dict[str, Any]:
    """
    with_windows=True → fetch 1m candles for every CE/PE in ATM±3 (heavier).
    Call every ~15s from UI; live OI/LTP can refresh more often via same endpoint
    when with_windows=False for a lighter tick (optional).
    """
    if not ux.enabled():
        return {
            "ok": False,
            "error": "UPSTOX_ACCESS_TOKEN required",
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
                    "error": "Chain empty — token / expiry / market",
                    "rows": [],
                }
            )
            continue

        mp_data = ux.max_pain_api(key, "current_week")
        mp = mp_data.get("max_pain") if isinstance(mp_data, dict) else None
        if isinstance(mp_data, dict) and mp_data.get("expiry_date"):
            expiry = expiry or str(mp_data.get("expiry_date"))[:10]
        if mp is None:
            mp = ux.compute_max_pain_from_rows(rows)

        walls = ux.walls_from_rows(rows, spot)
        ce_wall = walls.get("ce_wall_strike")
        pe_wall = walls.get("pe_wall_strike")
        atm = ux.atm_row(rows, spot)
        atm_strike = atm["strike"] if atm else None
        band_rows = _band_rows(rows, spot, n=band)

        table = []
        for r in band_rows:
            strike = r["strike"]
            marks, mark_class = [], ""
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
                mark_class = (mark_class + " maxpain").strip() if mark_class else "maxpain"

            ce_w = pe_w = {}
            if with_windows:
                if r.get("ce_key"):
                    try:
                        ce_w = ux.oi_premium_windows(r["ce_key"])
                    except Exception as e:
                        log.warning("ce windows %s: %s", strike, e)
                if r.get("pe_key"):
                    try:
                        pe_w = ux.oi_premium_windows(r["pe_key"])
                    except Exception as e:
                        log.warning("pe windows %s: %s", strike, e)

            ce = _side_block(r.get("ce_oi"), r.get("ce_ltp"), ce_w)
            pe = _side_block(r.get("pe_oi"), r.get("pe_ltp"), pe_w)

            # day Δ also from chain prev_oi as backup
            if ce.get("oi_open", {}).get("at") is None and r.get("ce_prev_oi"):
                d = _delta(ce.get("oi_now"), r.get("ce_prev_oi"))
                ce["oi_open"] = {
                    "at": r.get("ce_prev_oi"),
                    "at_disp": f"{r['ce_prev_oi']:,.0f}",
                    "chg": d,
                    "chg_pct": _pct(ce.get("oi_now"), r.get("ce_prev_oi")),
                    "disp": _chg_str(d, _pct(ce.get("oi_now"), r.get("ce_prev_oi"))),
                }
            if pe.get("oi_open", {}).get("at") is None and r.get("pe_prev_oi"):
                d = _delta(pe.get("oi_now"), r.get("pe_prev_oi"))
                pe["oi_open"] = {
                    "at": r.get("pe_prev_oi"),
                    "at_disp": f"{r['pe_prev_oi']:,.0f}",
                    "chg": d,
                    "chg_pct": _pct(pe.get("oi_now"), r.get("pe_prev_oi")),
                    "disp": _chg_str(d, _pct(pe.get("oi_now"), r.get("pe_prev_oi"))),
                }

            table.append(
                {
                    "strike": strike,
                    "marks": marks,
                    "mark_class": mark_class,
                    "ce": ce,
                    "pe": pe,
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

        # time labels from first ATM row windows if any
        time_labels = {"now": "now", "m5": "5m ago", "m15": "15m ago", "m30": "30m ago", "open": "day open"}
        for row in table:
            if row.get("marks") and "ATM" in row["marks"]:
                ce = row["ce"]
                time_labels = {
                    "now": ce.get("ts_now") or "now",
                    "m5": ce.get("ts_5m") or "5m ago",
                    "m15": ce.get("ts_15m") or "15m ago",
                    "m30": ce.get("ts_30m") or "30m ago",
                    "open": ce.get("ts_open") or "~9:15",
                }
                break

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
                "tot_ce_day": _chg_str(tot_ce_d),
                "tot_pe_day": _chg_str(tot_pe_d),
                "time_labels": time_labels,
                "read": read,
                "rows": table,
            }
        )

    return {"ok": True, "boards": boards, "source": "upstox", "with_windows": with_windows}
