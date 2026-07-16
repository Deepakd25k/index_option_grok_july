"""
Pro Edge — FII-only institutional signals + Upstox option/futures structure.

NO duplicates of Sheet tab (no Nasdaq/Dow/VIX level/Europe/cash FII display).
Pro-only blocks:
  1. FII futures + options book (NSE participant) with day Δ
  2. Upstox option structure: max pain, PCR, CE/PE walls (Nifty & BankNifty)
  3. Upstox index futures ORB + volume vs 20D
  4. FII OI next-day scorecard (from fii_week)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app import upstox_api as ux
from app.nse_oi import download_oi_for_date, enrich_participant, parse_participant_csv

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")


def _card(
    id_: str,
    title: str,
    value: Any,
    meaning: str,
    why: str,
    signal: str = "",
) -> dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "value": value if value not in (None, "") else "—",
        "meaning": meaning,
        "why": why,
        "signal": signal or "",
    }


def _fmt_int(n: Any) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(float(n)):,}"
    except (TypeError, ValueError):
        return str(n)


def _fmt_signed(n: Any, digits: int = 0) -> str:
    if n is None:
        return "—"
    try:
        x = float(n)
    except (TypeError, ValueError):
        return str(n)
    sign = "+" if x > 0 else ""
    if digits == 0:
        return f"{sign}{int(round(x)):,}"
    return f"{sign}{x:.{digits}f}"


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


# ── FII-only participant series ──────────────────────────────
def _fii_series(lookback: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    d = datetime.now(TZ).date()
    tried = 0
    while len(rows) < lookback and tried < 14:
        tried += 1
        if d.weekday() >= 5:
            d -= timedelta(days=1)
            continue
        got = download_oi_for_date(d)
        d -= timedelta(days=1)
        if not got:
            continue
        text, ymd = got
        try:
            raw = parse_participant_csv(text)
        except Exception:
            continue
        if "FII" not in raw:
            continue
        e = enrich_participant(raw["FII"])
        rows.append(
            {
                "oi_date": ymd,
                "fut_long": e.get("idx_fut_long"),
                "fut_short": e.get("idx_fut_short"),
                "fut_net": e.get("idx_fut_net"),
                "fut_ratio": e.get("idx_fut_ratio"),
                "fut_long_pct": e.get("idx_fut_long_pct"),
                "fut_short_pct": e.get("idx_fut_short_pct"),
                "fut_long_display": e.get("idx_fut_long_display"),
                "fut_short_display": e.get("idx_fut_short_display"),
                "call_long": e.get("option_index_call_long"),
                "call_short": e.get("option_index_call_short"),
                "put_long": e.get("option_index_put_long"),
                "put_short": e.get("option_index_put_short"),
                "opt_pcr_short": e.get("idx_opt_pcr_short"),
            }
        )
    return rows


def build_fii_only(series: list[dict] | None = None) -> dict[str, Any]:
    series = series if series is not None else _fii_series(6)
    if not series:
        return {
            "section": "FII book (futures + options)",
            "cards": [],
            "note": "NSE FII participant OI ~7:00–7:30 PM IST ke baad aata hai.",
        }

    cur, prev = series[0], (series[1] if len(series) > 1 else {})
    cards: list[dict] = []

    # Futures
    for key, title, meaning, why in (
        (
            "fut_long",
            "FII Idx Fut Long",
            "FII long open interest in index futures (contracts).",
            "Rising long OI + price up = trend confirm. Absolute level alone kam useful; Δ dekho.",
        ),
        (
            "fut_short",
            "FII Idx Fut Short",
            "FII short OI in index futures.",
            "High short % = hedge/bearish. Covering (short ↓) = squeeze risk next session.",
        ),
    ):
        val = cur.get(key)
        dlt = _delta(val, prev.get(key))
        disp = cur.get(f"{key}_display") or _fmt_int(val)
        if dlt is not None:
            disp = f"{disp} · Δ {_fmt_signed(dlt)}"
        sig = ""
        if dlt is not None:
            if key == "fut_long" and dlt > 0:
                sig = "Long build"
            if key == "fut_short" and dlt > 0:
                sig = "Short build"
            if key == "fut_short" and dlt < 0:
                sig = "Short covering"
        cards.append(_card(key, title, disp, meaning, why, sig))

    net = cur.get("fut_net")
    d_net = _delta(net, prev.get("fut_net"))
    cards.append(
        _card(
            "fut_net",
            "FII Idx Fut Net (L−S)",
            f"{_fmt_signed(net)} · Δ {_fmt_signed(d_net)}" if d_net is not None else _fmt_signed(net),
            "Long contracts minus short contracts.",
            "Net < 0 = net short book (common). Day-over-day ΔNet > 0 = covering/bullish tilt for next day.",
            "Net short" if (net or 0) < 0 else "Net long",
        )
    )
    ratio = cur.get("fut_ratio")
    cards.append(
        _card(
            "fut_ratio",
            "FII Long/Short ratio",
            f"{ratio:.3f}" if ratio is not None else "—",
            "Long ÷ Short.",
            "< 1 net short; rising ratio = less short-heavy. Retail almost never tracks this daily.",
        )
    )

    # Options book — FII only
    for key, title, meaning, why in (
        ("call_long", "FII Idx Call Long", "Long index calls.", "Upside participation / bullish directional."),
        ("call_short", "FII Idx Call Short", "Short index calls.", "Premium sell / resistance supply overhead."),
        ("put_long", "FII Idx Put Long", "Long index puts.", "Downside hedge or bearish bet."),
        ("put_short", "FII Idx Put Short", "Short index puts.", "Bullish put-write support."),
    ):
        val = cur.get(key)
        dlt = _delta(val, prev.get(key))
        disp = _fmt_int(val)
        if dlt is not None:
            disp = f"{disp} · Δ {_fmt_signed(dlt)}"
        sig = ""
        if dlt is not None and dlt > 0:
            if key in ("call_long", "put_short"):
                sig = "Bullish tilt"
            else:
                sig = "Defensive tilt"
        cards.append(_card(key, title, disp, meaning, why, sig))

    pcr = cur.get("opt_pcr_short")
    pcr_p = prev.get("opt_pcr_short")
    pcr_disp = f"{pcr:.3f}" if pcr is not None else "—"
    if pcr is not None and pcr_p is not None:
        pcr_disp += f" · Δ {_fmt_signed(pcr - pcr_p, 3)}"
    cards.append(
        _card(
            "opt_pcr",
            "FII Opt PCR (short OI)",
            pcr_disp,
            "FII put short OI ÷ call short OI.",
            "Rising PCR → more put writing (cushion). Falling → call writing / less support.",
        )
    )

    return {
        "section": "FII book (futures + options)",
        "oi_date": cur.get("oi_date"),
        "cards": cards,
        "note": "Source: NSE fao_participant_oi CSV · FII row only · Δ = vs previous session",
    }


# ── Upstox option structure ──────────────────────────────────
def build_upstox_option_structure() -> dict[str, Any]:
    cards: list[dict] = []
    if not ux.enabled():
        return {
            "section": "Option structure (Upstox)",
            "cards": [
                _card(
                    "oc_gate",
                    "Max pain / walls / PCR",
                    "Set UPSTOX_ACCESS_TOKEN",
                    "Live chain + official max-pain from Upstox API.",
                    "Vercel/local env me token lagao — phir Nifty & BankNifty walls unlock.",
                )
            ],
            "note": "API: /v2/option/chain · /v2/market/max-pain · expiry=current_week",
        }

    for label, key in (
        ("Nifty", ux.IDX["nifty"]),
        ("BankNifty", ux.IDX["banknifty"]),
    ):
        exp = "current_week"
        chain = ux.option_chain(key, exp)
        spot, rows, exp_resolved = ux.parse_chain_rows(chain)
        mp_data = ux.max_pain_api(key, exp)
        mp = None
        spot_close = spot
        if isinstance(mp_data, dict):
            mp = mp_data.get("max_pain")
            if mp_data.get("spot_closing_price") is not None:
                try:
                    spot_close = float(mp_data["spot_closing_price"])
                except (TypeError, ValueError):
                    pass
            exp_resolved = exp_resolved or str(mp_data.get("expiry_date") or "")[:10]
        if mp is None and rows:
            mp = ux.compute_max_pain_from_rows(rows)

        walls = ux.walls_from_rows(rows, spot or spot_close)

        if not rows and mp is None:
            cards.append(
                _card(
                    f"{label}_oc",
                    f"{label} chain",
                    "No data",
                    "Upstox chain empty — check token / market hours / expiry.",
                    "Token must have market data scope.",
                )
            )
            continue

        sp = spot or spot_close
        cards.append(
            _card(
                f"{label}_spot",
                f"{label} spot (chain)",
                f"{sp:,.2f}" if sp else "—",
                "Underlying spot from Upstox option chain.",
                "Distance math for walls & max pain uses this level.",
            )
        )
        dist_mp = (
            round(100 * (float(mp) - float(sp)) / float(sp), 2)
            if mp is not None and sp
            else None
        )
        cards.append(
            _card(
                f"{label}_maxpain",
                f"{label} max pain",
                (
                    f"{float(mp):,.0f} ({dist_mp:+.2f}% vs spot) · exp {exp_resolved or exp}"
                    if mp is not None and dist_mp is not None
                    else (_fmt_int(mp) if mp is not None else "—")
                ),
                "Strike where option writers lose least at expiry (Upstox max-pain API / chain calc).",
                "Expiry week me spot often drifts toward max pain — not a daily magnet.",
                "Near expiry mean-revert risk" if dist_mp is not None and abs(dist_mp) > 0.8 else "",
            )
        )
        cards.append(
            _card(
                f"{label}_pcr",
                f"{label} chain PCR (OI)",
                f"{walls.get('pcr')}" if walls.get("pcr") is not None else "—",
                "Total put OI ÷ total call OI on near expiry chain.",
                "High PCR = put-heavy support bias; low PCR = call-heavy overhead.",
            )
        )
        if walls.get("ce_wall_strike") is not None:
            cards.append(
                _card(
                    f"{label}_ce_wall",
                    f"{label} Call wall",
                    f"{walls['ce_wall_strike']:,.0f} · OI {_fmt_int(walls.get('ce_wall_oi'))} · {walls.get('dist_ce_pct')}% away",
                    "Highest call OI strike — resistance / pin zone.",
                    "Rejection at wall = range high; volume break = cover fuel.",
                )
            )
        if walls.get("pe_wall_strike") is not None:
            cards.append(
                _card(
                    f"{label}_pe_wall",
                    f"{label} Put wall",
                    f"{walls['pe_wall_strike']:,.0f} · OI {_fmt_int(walls.get('pe_wall_oi'))} · {walls.get('dist_pe_pct')}% away",
                    "Highest put OI strike — support / pin zone.",
                    "Hold = dip-buy zone; clean break = stop cascade risk.",
                )
            )

    return {
        "section": "Option structure (Upstox)",
        "cards": cards,
        "note": "Upstox: option/chain + market/max-pain · expiry current_week",
    }


# ── Futures ORB + volume ─────────────────────────────────────
def build_futures_orb() -> dict[str, Any]:
    cards: list[dict] = []
    if not ux.enabled():
        return {
            "section": "Index futures ORB & volume",
            "cards": [
                _card(
                    "orb_gate",
                    "Futures ORB / volume",
                    "Set UPSTOX_ACCESS_TOKEN",
                    "Nifty & BankNifty **futures** first-30m range + volume vs 20D.",
                    "Cash index volume ignore — sirf FO futures.",
                )
            ],
            "note": "Needs Upstox market data + FO instruments",
        }

    for label, search in (("Nifty", "NIFTY"), ("BankNifty", "BANKNIFTY")):
        fut = ux.nearest_index_future(search)
        if not fut:
            cards.append(
                _card(
                    f"fut_{label}",
                    f"{label} futures",
                    "Contract not resolved",
                    "Could not find nearest FUTIDX in Upstox instruments file.",
                    "Will retry on next refresh; check NSE FO segment availability.",
                )
            )
            continue
        ik = fut.get("instrument_key")
        ts = fut.get("trading_symbol") or ik
        exp = str(fut.get("expiry") or "")[:10]
        cards.append(
            _card(
                f"fut_key_{label}",
                f"{label} near futures",
                f"{ts} · exp {exp}",
                "Nearest unexpired index future (Upstox instruments).",
                "All ORB/volume math uses this contract key.",
            )
        )
        daily = ux.historical_day(ik, days=30) if ik else []
        vols = []
        for c in daily:
            if isinstance(c, (list, tuple)) and len(c) >= 6:
                try:
                    vols.append(float(c[5] or 0))
                except (TypeError, ValueError):
                    pass
        if vols:
            last_v = vols[-1]
            base = vols[-21:-1] if len(vols) > 1 else vols[:-1]
            avg = (sum(base) / len(base)) if base else None
            ratio = (last_v / avg) if avg else None
            disp = f"Vol {_fmt_int(last_v)}"
            if ratio is not None:
                disp += f" ({ratio:.2f}× vs ~20D)"
            cards.append(
                _card(
                    f"vol_{label}",
                    f"{label} fut volume vs 20D",
                    disp,
                    "Today’s futures volume vs prior ~20 sessions on same contract series.",
                    "≥1.3× = high participation day (trend ORB more reliable). <0.7× = quiet/range.",
                    "High volume" if (ratio or 0) >= 1.3 else ("Quiet" if (ratio or 99) < 0.7 else "Average"),
                )
            )
        intra = ux.intraday(ik, "30minute") if ik else []
        # pick earliest bar of today if possible
        bar = None
        if intra:
            # Upstox often returns newest first
            candidates = [c for c in intra if isinstance(c, (list, tuple)) and len(c) >= 5]
            if candidates:
                bar = candidates[-1]  # oldest in list ≈ first bar of day when full day
                # if timestamps available prefer 09:15 bucket
                for c in candidates:
                    ts0 = str(c[0])
                    if "09:15" in ts0 or "T09:15" in ts0 or "09:30" in ts0:
                        bar = c
                        break
        if bar:
            try:
                o, h, l_ = float(bar[1]), float(bar[2]), float(bar[3])
                cards.append(
                    _card(
                        f"orb_{label}",
                        f"{label} fut first 30m OR",
                        f"O {o:,.2f} · H {h:,.2f} · L {l_:,.2f} · width {h - l_:,.2f}",
                        "Opening range from first 30-minute futures candle.",
                        "Break of OR high/low with volume = ORB trend entry; fail = range day.",
                    )
                )
            except (TypeError, ValueError, IndexError):
                pass

    return {
        "section": "Index futures ORB & volume",
        "cards": cards,
        "note": "Upstox FO nearest future · historical day + intraday 30m",
    }


def build_scorecard(fii_week: dict | None) -> dict[str, Any]:
    summary = (fii_week or {}).get("summary") or {}
    cards = []
    if summary.get("bias_total"):
        cards.append(
            _card(
                "score_bias",
                "FII fut bias → next day hit-rate",
                f"{summary.get('bias_accuracy_pct')}% ({summary.get('bias_hits')}/{summary.get('bias_total')})",
                "Net long/short bias vs next session Nifty direction.",
                "Measured edge — most traders never log this. <45% long stretch → fade or ignore bias.",
            )
        )
        cards.append(
            _card(
                "score_flow",
                "FII ΔNet flow → next day hit-rate",
                f"{summary.get('flow_accuracy_pct')}% ({summary.get('flow_hits')}/{summary.get('flow_total')})",
                "Day-over-day change in FII net futures vs next day.",
                "Covering (ΔNet↑) vs adding short (ΔNet↓). Often cleaner than static net.",
            )
        )
    else:
        cards.append(
            _card(
                "score_empty",
                "FII next-day scorecard",
                "Refresh once after OI history loads",
                "Auto hit-rate from FII OI week engine.",
                "No manual journal — builds from NSE OI + Nifty closes.",
            )
        )
    return {
        "section": "FII edge scorecard",
        "cards": cards,
        "note": "Linked to FII OI tab week engine — not duplicated index prices",
    }


def build_pro_edge(context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    fii_week = context.get("fii_week")

    fii_block = build_fii_only()
    opt_block = build_upstox_option_structure()
    orb_block = build_futures_orb()
    score_block = build_scorecard(fii_week)

    signals = []
    for block in (fii_block, opt_block, orb_block):
        for c in block.get("cards") or []:
            if c.get("signal"):
                signals.append(f"{c['title']}: {c['signal']}")

    return {
        "built_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S IST"),
        "headline": "Pro Edge — FII only",
        "blurb": (
            "Sirf institutional / structure data jo Sheet pe nahi hai: "
            "FII fut+opt book with Δ, Upstox max pain & OI walls, "
            "index futures ORB/volume, FII next-day hit-rate. "
            "Koi Nasdaq/Dow/VIX repeat nahi."
        ),
        "active_signals": signals[:10],
        "blocks": [fii_block, opt_block, orb_block, score_block],
    }
