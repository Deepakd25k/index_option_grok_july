"""
Sticky Resistance / Support strength from ATM±3 OI board.

Problem: chain refreshes every ~3s → raw "weak/strong" would flicker.
Solution:
  - Primary: wall-strike OI Δ15m + Δ30m (not 5m for flips)
  - Optional confirm: premium Δ (OI↓ Prem↑ = covering = weak)
  - Hysteresis bands so small noise doesn't flip
  - Sticky state: min hold ~100s; flip only if opposite raw holds that long

Labels: WEAK | STRONG | NEUTRAL
"""
from __future__ import annotations

import time
from typing import Any

# ── thresholds (pct of OI at wall) ─────────────────────────────
# enter STRONG if 30m ≥ +ENTER and 15m not opposing hard
# enter WEAK   if 30m ≤ −ENTER and 15m not opposing hard
ENTER_PCT = 1.2  # % OI change over 30m to declare
EXIT_PCT = 0.4  # hysteresis: leave WEAK/STRONG only past this the other way
# 15m must not strongly disagree (same sign or flat)
M15_AGREE_PCT = 0.3

# sticky: seconds opposite raw must persist before flip
HOLD_SEC = 100.0
# minimum time in a state before any flip allowed
MIN_HOLD_SEC = 45.0

# in-process sticky memory (per process / serverless cold start resets)
_STATE: dict[str, dict[str, Any]] = {}


def _pct(chg: float | None, at: float | None, now: float | None) -> float | None:
    """Prefer packed chg_pct; else compute from levels."""
    if chg is not None and at not in (None, 0):
        try:
            return round(100.0 * float(chg) / float(at), 2)
        except Exception:
            pass
    if now is not None and at not in (None, 0):
        try:
            return round(100.0 * (float(now) - float(at)) / float(at), 2)
        except Exception:
            pass
    return None


def _side_raw(side: dict | None) -> dict[str, Any]:
    """Raw WEAK/STRONG/NEUTRAL from one CE or PE side at wall strike."""
    side = side or {}
    o15 = side.get("oi_15m") or {}
    o30 = side.get("oi_30m") or {}
    o5 = side.get("oi_5m") or {}
    p30 = side.get("prem_30m") or {}
    p5 = side.get("prem_5m") or {}

    p15 = o15.get("chg_pct")
    if p15 is None:
        p15 = _pct(o15.get("chg"), o15.get("at"), side.get("oi_now"))
    p30v = o30.get("chg_pct")
    if p30v is None:
        p30v = _pct(o30.get("chg"), o30.get("at"), side.get("oi_now"))
    p5v = o5.get("chg_pct")
    if p5v is None:
        p5v = _pct(o5.get("chg"), o5.get("at"), side.get("oi_now"))

    prem30 = p30.get("chg")
    prem5 = p5.get("chg")

    raw = "NEUTRAL"
    conf = 40
    why = "15m/30m OI mixed or flat"

    if p30v is not None:
        # STRONG: OI building on wall (writers adding)
        if p30v >= ENTER_PCT and (p15 is None or p15 >= -M15_AGREE_PCT):
            raw = "STRONG"
            conf = 55
            why = f"OI 30m {p30v:+.1f}% building"
            if p15 is not None and p15 >= M15_AGREE_PCT:
                conf += 10
                why += f", 15m {p15:+.1f}%"
            # writing confirm: prem down while OI up
            if prem30 is not None and prem30 < 0:
                conf += 10
                why += " · prem↓ write"
        # WEAK: OI unwinding on wall
        elif p30v <= -ENTER_PCT and (p15 is None or p15 <= M15_AGREE_PCT):
            raw = "WEAK"
            conf = 55
            why = f"OI 30m {p30v:+.1f}% unwind"
            if p15 is not None and p15 <= -M15_AGREE_PCT:
                conf += 10
                why += f", 15m {p15:+.1f}%"
            # covering: prem up while OI down
            if prem30 is not None and prem30 > 0:
                conf += 10
                why += " · prem↑ cover"
        else:
            why = f"OI 30m {p30v:+.1f}% (need ±{ENTER_PCT}% + 15m agree)"

    conf = min(95, conf)
    return {
        "raw": raw,
        "conf": conf,
        "why": why,
        "oi_pct_5m": p5v,
        "oi_pct_15m": p15,
        "oi_pct_30m": p30v,
        "oi_chg_5m": o5.get("chg"),
        "oi_chg_15m": o15.get("chg"),
        "oi_chg_30m": o30.get("chg"),
        "prem_chg_5m": prem5,
        "prem_chg_30m": prem30,
        "oi_now": side.get("oi_now"),
        "oi_now_disp": side.get("oi_now_disp"),
    }


def _hysteresis_apply(sticky: str, raw: str, p30: float | None) -> str:
    """
    Soften raw using sticky + exit band.
    If sticky WEAK, need clear STRONG (p30 high) to propose STRONG; mild noise → stay WEAK.
    """
    if p30 is None:
        return sticky if sticky else "NEUTRAL"

    if sticky == "WEAK":
        # only leave WEAK toward NEUTRAL/STRONG if OI recovered past -EXIT
        if p30 <= -EXIT_PCT:
            return "WEAK"  # still weak zone
        if p30 >= ENTER_PCT:
            return "STRONG"
        return "NEUTRAL" if raw == "NEUTRAL" else raw

    if sticky == "STRONG":
        if p30 >= EXIT_PCT:
            return "STRONG"
        if p30 <= -ENTER_PCT:
            return "WEAK"
        return "NEUTRAL" if raw == "NEUTRAL" else raw

    # sticky NEUTRAL or empty: trust raw (already thresholded)
    return raw


def _stick_one(key: str, proposed: str, now: float) -> dict[str, Any]:
    """
    key like "Nifty:R"
    Hold current label MIN_HOLD_SEC; flip only if proposed differs and
    has been continuous for HOLD_SEC.

    Exception: NEUTRAL → first clear WEAK/STRONG adopts after short confirm (~12s)
    so cold start is not stuck blank for 100s.
    """
    st = _STATE.get(key) or {
        "label": "NEUTRAL",
        "since": now,
        "pending": None,
        "pending_since": None,
        "ever_set": False,
    }
    cur = st.get("label") or "NEUTRAL"

    if proposed == cur:
        st["pending"] = None
        st["pending_since"] = None
        st["label"] = cur
        _STATE[key] = st
        return st

    # First meaningful call out of NEUTRAL: short confirm only (~12s)
    first_out = cur == "NEUTRAL" and proposed in ("WEAK", "STRONG") and not st.get("ever_set")
    need_hold = 12.0 if first_out else HOLD_SEC
    min_hold = 0.0 if first_out else MIN_HOLD_SEC

    age = now - float(st.get("since") or now)
    if age < min_hold:
        if st.get("pending") != proposed:
            st["pending"] = proposed
            st["pending_since"] = now
        _STATE[key] = st
        return st

    if st.get("pending") != proposed:
        st["pending"] = proposed
        st["pending_since"] = now
        _STATE[key] = st
        return st

    pend_age = now - float(st.get("pending_since") or now)
    if pend_age >= need_hold:
        st["label"] = proposed
        st["since"] = now
        st["pending"] = None
        st["pending_since"] = None
        if proposed in ("WEAK", "STRONG"):
            st["ever_set"] = True
    _STATE[key] = st
    return st


def _fmt_heat_oi(chg: float | None) -> str:
    if chg is None:
        return "—"
    from app.oi_board import _fmt_oi

    return _fmt_oi(chg, signed=True)


def evaluate_board(
    label: str,
    table: list[dict],
    ce_wall: float | None,
    pe_wall: float | None,
    spot: float | None,
) -> dict[str, Any]:
    """
    Build sticky R/S strength block for one underlying board.
    """
    now = time.time()

    def find_row(strike: float | None) -> dict | None:
        if strike is None:
            return None
        for r in table:
            if abs(float(r["strike"]) - float(strike)) < 0.01:
                return r
        # nearest
        if not table:
            return None
        return min(table, key=lambda r: abs(float(r["strike"]) - float(strike)))

    r_row = find_row(ce_wall)
    s_row = find_row(pe_wall)
    r_raw = _side_raw((r_row or {}).get("ce"))
    s_raw = _side_raw((s_row or {}).get("pe"))

    r_prop = _hysteresis_apply(
        (_STATE.get(f"{label}:R") or {}).get("label") or "NEUTRAL",
        r_raw["raw"],
        r_raw.get("oi_pct_30m"),
    )
    s_prop = _hysteresis_apply(
        (_STATE.get(f"{label}:S") or {}).get("label") or "NEUTRAL",
        s_raw["raw"],
        s_raw.get("oi_pct_30m"),
    )

    r_st = _stick_one(f"{label}:R", r_prop, now)
    s_st = _stick_one(f"{label}:S", s_prop, now)

    r_label = r_st["label"]
    s_label = s_st["label"]

    def age_str(st: dict) -> str:
        sec = max(0, int(now - float(st.get("since") or now)))
        if sec < 60:
            return f"{sec}s"
        return f"{sec // 60}m {sec % 60}s"

    def pending_note(st: dict) -> str | None:
        if st.get("pending") and st.get("pending") != st.get("label"):
            left = max(0, int(HOLD_SEC - (now - float(st.get("pending_since") or now))))
            return f"→ {st['pending']} in ~{left}s"
        return None

    r_strike = float(ce_wall) if ce_wall is not None else None
    s_strike = float(pe_wall) if pe_wall is not None else None

    # distance of spot to walls (pts)
    r_dist = (r_strike - spot) if (r_strike is not None and spot is not None) else None
    s_dist = (spot - s_strike) if (s_strike is not None and spot is not None) else None

    # combined plan line
    plan_bits = []
    if r_label == "WEAK" and s_label == "STRONG":
        plan_bits.append("Bias: dips buy / upside free-er (weak R + strong S)")
    elif r_label == "STRONG" and s_label == "WEAK":
        plan_bits.append("Bias: rips sell / downside free-er (strong R + weak S)")
    elif r_label == "WEAK" and s_label == "WEAK":
        plan_bits.append("Both walls soft — breakout either side, trail tight")
    elif r_label == "STRONG" and s_label == "STRONG":
        plan_bits.append("Range box — scalp 25–35 into walls, avoid mid chase")
    else:
        plan_bits.append("Mixed / neutral walls — wait 15–30m OI confirm")

    if r_dist is not None and r_dist < 40 and r_label == "STRONG":
        plan_bits.append(f"Near hard R {r_strike:,.0f}")
    if s_dist is not None and s_dist < 40 and s_label == "STRONG":
        plan_bits.append(f"Near hard S {s_strike:,.0f}")
    if r_dist is not None and r_dist < 40 and r_label == "WEAK":
        plan_bits.append(f"Near soft R {r_strike:,.0f} — break watch")
    if s_dist is not None and s_dist < 40 and s_label == "WEAK":
        plan_bits.append(f"Near soft S {s_strike:,.0f} — break watch")

    heat = {
        "ce_5m": _fmt_heat_oi(r_raw.get("oi_chg_5m")),
        "pe_5m": _fmt_heat_oi(s_raw.get("oi_chg_5m")),
        "ce_5m_pct": r_raw.get("oi_pct_5m"),
        "pe_5m_pct": s_raw.get("oi_pct_5m"),
        "note": "5m heat only — does not flip sticky R/S",
    }

    return {
        "ok": True,
        "resistance": {
            "label": r_label,
            "raw": r_raw["raw"],
            "strike": r_strike,
            "since": age_str(r_st),
            "pending": pending_note(r_st),
            "conf": r_raw["conf"] if r_label == r_raw["raw"] else max(40, r_raw["conf"] - 15),
            "why": r_raw["why"],
            "oi_pct_15m": r_raw.get("oi_pct_15m"),
            "oi_pct_30m": r_raw.get("oi_pct_30m"),
            "oi_now_disp": r_raw.get("oi_now_disp"),
        },
        "support": {
            "label": s_label,
            "raw": s_raw["raw"],
            "strike": s_strike,
            "since": age_str(s_st),
            "pending": pending_note(s_st),
            "conf": s_raw["conf"] if s_label == s_raw["raw"] else max(40, s_raw["conf"] - 15),
            "why": s_raw["why"],
            "oi_pct_15m": s_raw.get("oi_pct_15m"),
            "oi_pct_30m": s_raw.get("oi_pct_30m"),
            "oi_now_disp": s_raw.get("oi_now_disp"),
        },
        "heat_5m": heat,
        "plan": " · ".join(plan_bits),
        "rules": {
            "enter_pct": ENTER_PCT,
            "hold_sec": HOLD_SEC,
            "min_hold_sec": MIN_HOLD_SEC,
            "primary": "OI Δ15m+Δ30m at CE wall (R) / PE wall (S)",
            "ignore_for_flip": "5m OI (heat only)",
        },
    }
