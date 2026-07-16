"""
FII next-day playbook — simple conclusion for traders.

Combines:
  - FII fut net + day Δ (covering vs adding short)
  - FII options tilts (call/put long/short Δ)
  - Historical hit-rate from fii_week summary
  - Optional gap / overnight context from snapshot
"""
from __future__ import annotations

from typing import Any


def _sgn(x: float | None) -> int:
    if x is None:
        return 0
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def build_fii_conclusion(
    fii_series: list[dict] | None,
    fii_week: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """
    Returns a big conclusion object for FII tab header.
    bias: BULLISH | BEARISH | NEUTRAL
    confidence: 0-100 (heuristic probability-style score, not statistical guarantee)
    """
    context = context or {}
    fii_week = fii_week or {}
    summary = fii_week.get("summary") or {}

    if not fii_series:
        return {
            "bias": "NEUTRAL",
            "confidence": 0,
            "headline": "FII data pending",
            "one_liner": "NSE FII OI ~7:00–7:30 PM ke baad aata hai. Refresh after that.",
            "bullets": [],
            "plan_pre": "Wait for FII OI print before sizing open bias.",
            "plan_live": "Trade only structure + ORB until FII updates.",
            "color": "neutral",
        }

    cur = fii_series[0]
    prev = fii_series[1] if len(fii_series) > 1 else {}

    net = cur.get("fut_net")
    d_net = None
    if net is not None and prev.get("fut_net") is not None:
        d_net = float(net) - float(prev["fut_net"])

    d_long = None
    d_short = None
    if cur.get("fut_long") is not None and prev.get("fut_long") is not None:
        d_long = float(cur["fut_long"]) - float(prev["fut_long"])
    if cur.get("fut_short") is not None and prev.get("fut_short") is not None:
        d_short = float(cur["fut_short"]) - float(prev["fut_short"])

    # Options day tilts
    opt_bull = 0
    opt_bear = 0
    bullets_opt = []
    for key, bull_when_up, label in (
        ("call_long", True, "Call long"),
        ("put_short", True, "Put short"),
        ("put_long", False, "Put long"),
        ("call_short", False, "Call short"),
    ):
        if cur.get(key) is None or prev.get(key) is None:
            continue
        d = float(cur[key]) - float(prev[key])
        if abs(d) < 1000:
            continue
        if d > 0:
            if bull_when_up:
                opt_bull += 1
                bullets_opt.append(f"{label} build (+{int(d):,})")
            else:
                opt_bear += 1
                bullets_opt.append(f"{label} build (+{int(d):,})")
        else:
            bullets_opt.append(f"{label} cut ({int(d):,})")

    # Score: +1 bull, -1 bear
    score = 0.0
    reasons: list[str] = []

    # Flow ΔNet is primary (covering)
    if d_net is not None:
        if d_net > 5000:
            score += 2.0
            reasons.append(f"FII covering / net improved (ΔNet {int(d_net):+,})")
        elif d_net > 0:
            score += 1.0
            reasons.append(f"Mild covering (ΔNet {int(d_net):+,})")
        elif d_net < -5000:
            score -= 2.0
            reasons.append(f"FII adding short aggressively (ΔNet {int(d_net):+,})")
        elif d_net < 0:
            score -= 1.0
            reasons.append(f"Mild short add (ΔNet {int(d_net):+,})")

    if d_short is not None and d_short < -3000:
        score += 1.0
        reasons.append(f"Short covering in futures ({int(d_short):+,} short OI)")
    if d_short is not None and d_short > 3000:
        score -= 1.0
        reasons.append(f"Fresh short build ({int(d_short):+,})")
    if d_long is not None and d_long > 3000:
        score += 0.5
        reasons.append(f"Long build ({int(d_long):+,})")

    score += 0.5 * opt_bull
    score -= 0.5 * opt_bear
    reasons.extend(bullets_opt[:3])

    # Historical hit-rate adjusts confidence, not direction alone
    flow_acc = summary.get("flow_accuracy_pct")
    bias_acc = summary.get("bias_accuracy_pct")
    hist = flow_acc if flow_acc is not None else bias_acc

    # Gap context (optional)
    gap_pct = context.get("gap_pct")
    gap_cat = context.get("gap_category") or ""
    if gap_pct is not None:
        gp = float(gap_pct) * 100 if abs(float(gap_pct)) < 1 else float(gap_pct)
        if gp > 0.3 and score > 0:
            score += 0.5
            reasons.append(f"Gap up {gap_cat or ''} aligns with bullish FII flow")
        if gp < -0.3 and score < 0:
            score -= 0.5
            reasons.append(f"Gap down {gap_cat or ''} aligns with bearish FII flow")
        if gp > 0.3 and score < 0:
            reasons.append("⚠ Gap up but FII flow bearish — fade-open / trap risk")
        if gp < -0.3 and score > 0:
            reasons.append("⚠ Gap down but FII covering — short-cover bounce risk")

    if score >= 1.5:
        bias = "BULLISH"
        color = "bull"
    elif score <= -1.5:
        bias = "BEARISH"
        color = "bear"
    else:
        bias = "NEUTRAL"
        color = "neutral"

    # Confidence heuristic 40–85
    conf = 50
    conf += min(20, abs(score) * 8)
    if hist is not None:
        conf = 0.6 * conf + 0.4 * float(hist)
    conf = int(max(40, min(85, round(conf))))

    if bias == "BULLISH":
        headline = f"Next day lean: BULLISH (~{conf}% conviction)"
        one = "FII flow favouring upside / covering — prefer buy-on-dip ORB longs over blind shorts."
        plan_pre = (
            f"Plan: Bias long. Gap small → buy ORH break. Gap large up → wait first 15m; "
            f"target scalp +25–35 pts, SL below OR low."
        )
        plan_live = (
            "Live: Only long scalps above VWAP/OR mid if flow not reversing. "
            "Avoid aggressive shorts unless structure (call wall) rejects."
        )
    elif bias == "BEARISH":
        headline = f"Next day lean: BEARISH (~{conf}% conviction)"
        one = "FII adding/holding short pressure — prefer sell-on-rise; bounce fades more likely."
        plan_pre = (
            f"Plan: Bias short. Gap small down → sell ORL break. Gap large down → wait trap bounce 15m; "
            f"scalp −25–35 pts, SL above OR high."
        )
        plan_live = (
            "Live: Short pulls into resistance / call wall. "
            "Don't bottom-pick without short-covering (Δ short OI↓)."
        )
    else:
        headline = f"Next day lean: RANGE / NEUTRAL (~{conf}% conviction)"
        one = "FII signal mixed — no high-probability directional edge from FII alone."
        plan_pre = (
            "Plan: Range day. Trade OR edges only; target 20–30 pts mean-reversion, not trend chase."
        )
        plan_live = (
            "Live: Fade extremes near put/call walls. Size half until FII/flow clearer."
        )

    if hist is not None:
        reasons.append(
            f"Recent FII signal hit-rate: flow {summary.get('flow_accuracy_pct')}% · bias {summary.get('bias_accuracy_pct')}%"
        )

    # Absolute net note (almost always short)
    if net is not None and net < 0:
        reasons.insert(
            0,
            f"Absolute book still net short ({int(net):,}) — direction = Δ (change), not absolute.",
        )

    return {
        "bias": bias,
        "confidence": conf,
        "headline": headline,
        "one_liner": one,
        "bullets": reasons[:8],
        "plan_pre": plan_pre,
        "plan_live": plan_live,
        "color": color,
        "oi_date": cur.get("oi_date"),
        "metrics": {
            "fut_net": net,
            "delta_net": d_net,
            "delta_long": d_long,
            "delta_short": d_short,
            "short_pct": cur.get("fut_short_pct"),
        },
    }
