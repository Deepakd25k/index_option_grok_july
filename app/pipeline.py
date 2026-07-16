"""Build one full snapshot — column-wise schema, zero manual fields."""
from __future__ import annotations

import logging
from typing import Any

from app.calendar_util import now_str, trading_status
from app.config import DAILY_COLUMNS, GAP_MEDIUM_PCT, GAP_SMALL_PCT
from app.fetchers import (
    fetch_mrchartist,
    fetch_upstox_all,
    fetch_yahoo_all,
    parse_fii_date,
    upstox_enabled,
)
from app.nse_oi import fetch_latest_participant_oi
from app.fii_trend import build_week_trend
from app import storage

log = logging.getLogger(__name__)


def gap_category(gap_pct: float | None) -> str:
    if gap_pct is None:
        return ""
    pct = abs(gap_pct) * 100.0
    if pct < GAP_SMALL_PCT:
        return "Small"
    if pct < GAP_MEDIUM_PCT:
        return "Medium"
    return "Large"


def _col(
    key: str,
    label: str,
    value: Any,
    display: Any = None,
    group: str = "",
    why: str = "",
    when: str = "",
    src: str = "",
    fmt: str = "number",
) -> dict[str, Any]:
    """One column definition for UI (column-wise structure)."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "display": display if display is not None else value,
        "group": group,
        "why": why,
        "when": when,
        "src": src,
        "fmt": fmt,
    }


def run_refresh() -> dict[str, Any]:
    trading = trading_status()
    ymd = trading["ymd"]
    sources: list[str] = []
    errors: list[str] = []

    upstox: dict[str, Any] = {}
    yahoo: dict[str, Any] = {}

    if upstox_enabled():
        try:
            upstox = fetch_upstox_all()
            sources.append("upstox")
        except Exception as e:
            errors.append(f"upstox:{e}")
            log.exception("upstox")
    else:
        sources.append("upstox:skipped(no_token)")

    try:
        yahoo = fetch_yahoo_all()
        sources.append("yahoo")
    except Exception as e:
        errors.append(f"yahoo:{e}")

    def pick(key: str) -> float | None:
        v = upstox.get(key)
        if v is not None:
            return float(v)
        v = yahoo.get(key)
        return float(v) if v is not None else None

    nifty = pick("nifty")
    bank = pick("banknifty")
    vix = pick("vix")
    gift = pick("gift")
    dow = pick("dow")
    spx = pick("spx")
    nasdaq = pick("nasdaq")
    nikkei = pick("nikkei")
    hsi = pick("hsi")
    ftse = pick("ftse")
    dax = pick("dax")
    cac = pick("cac")
    stoxx50 = pick("stoxx50")

    # ── Cash FII/DII (MrChartist free) ──
    fii_net = dii_net = None
    pcr = sentiment = None
    fii_date = api_updated = None
    inst = fetch_mrchartist()
    if inst:
        sources.append("mrchartist")
        fii_net = inst.get("fii_net")
        dii_net = inst.get("dii_net")
        pcr = inst.get("pcr")
        sentiment = inst.get("sentiment_score")
        fii_date = parse_fii_date(inst.get("date"))
        api_updated = inst.get("_updated_at")
    else:
        errors.append("mrchartist:failed")

    # ── NSE Participant OI (official CSV ~7–7:30 PM IST) ──
    nse_oi: dict[str, Any] = {}
    try:
        nse_oi = fetch_latest_participant_oi() or {}
        if nse_oi:
            sources.append("nse_participant_oi")
        else:
            errors.append("nse_oi:not_found_last_7d")
    except Exception as e:
        errors.append(f"nse_oi:{e}")
        log.exception("nse_oi")

    # Prefer NSE OI for FII long/short (actual contracts + %)
    fut_l = nse_oi.get("fii_idx_fut_long")
    fut_s = nse_oi.get("fii_idx_fut_short")
    fut_l_pct = nse_oi.get("fii_idx_fut_long_pct")
    fut_s_pct = nse_oi.get("fii_idx_fut_short_pct")
    fut_l_disp = nse_oi.get("fii_idx_fut_long_display")
    fut_s_disp = nse_oi.get("fii_idx_fut_short_display")
    fut_net = nse_oi.get("fii_idx_fut_net")
    fut_ratio = nse_oi.get("fii_idx_fut_ratio")
    fii_pcr_oi = nse_oi.get("fii_idx_opt_pcr_short")
    oi_date = nse_oi.get("oi_date")

    # Fallback: MrChartist participant numbers if NSE missing
    if fut_l is None and inst:
        fut_l = inst.get("fii_idx_fut_long")
        fut_s = inst.get("fii_idx_fut_short")
        if fut_l is not None and fut_s is not None and (fut_l + fut_s):
            total = float(fut_l) + float(fut_s)
            fut_l_pct = round(100 * float(fut_l) / total, 2)
            fut_s_pct = round(100 * float(fut_s) / total, 2)
            fut_l_disp = f"{int(fut_l):,} ({fut_l_pct:.2f}%)"
            fut_s_disp = f"{int(fut_s):,} ({fut_s_pct:.2f}%)"
            fut_net = float(fut_l) - float(fut_s)
            fut_ratio = (float(fut_l) / float(fut_s)) if fut_s else None

    # ── Gap ──
    gap_pts = gap_pct = None
    gap_cat = ""
    if gift is not None and nifty is not None and nifty != 0:
        gap_pts = gift - nifty
        gap_pct = gap_pts / nifty
        gap_cat = gap_category(gap_pct)

    # ── Column-wise structure (groups for UI) ──
    columns: list[dict[str, Any]] = [
        # Meta
        _col("date", "Date", ymd, group="Meta", why="Session date", when="Always", src="auto", fmt="text"),
        _col("day", "Day", trading["day"], group="Meta", why="Seasonality / which index bias", when="Always", src="auto", fmt="text"),
        _col(
            "is_trading",
            "Trading Day",
            trading["is_trading"],
            display="YES" if trading["is_trading"] else f"NO ({trading['holiday'] or trading['reason']})",
            group="Meta",
            why="Skip trade plan on holiday/weekend",
            when="Always",
            src="NSE calendar",
            fmt="text",
        ),
        # India indices
        _col("nifty", "Nifty 50 Close", nifty, group="India", why="Base for gap + trend reference", when="Pre-market + close", src="Upstox/Yahoo"),
        _col("banknifty", "BankNifty Close", bank, group="India", why="Bank-heavy days / which index to trade", when="Pre-market + close", src="Upstox/Yahoo"),
        _col("vix", "India VIX", vix, group="India", why="Low=range day, High=big moves / premium", when="Pre-market; spikes on events", src="Upstox/Yahoo"),
        # GIFT + Gap
        _col("gift", "GIFT Nifty", gift, group="Gap", why="Strongest overnight lead for Nifty open", when="Pre-market (early morning)", src="Upstox GLOBAL"),
        _col("gap_pts", "Expected Gap Pts", gap_pts, group="Gap", why="Open expectation in points", when="Pre-market after GIFT", src="GIFT−Nifty"),
        _col(
            "gap_pct",
            "Expected Gap %",
            gap_pct,
            display=f"{gap_pct * 100:.2f}%" if gap_pct is not None else None,
            group="Gap",
            why="ORB / gap-fill rules",
            when="Pre-market",
            src="formula",
            fmt="pct",
        ),
        _col("gap_category", "Gap Category", gap_cat, group="Gap", why="Small/Med/Large → different ORB plan", when="Pre-market", src="formula", fmt="text"),
        # US
        _col("dow", "Dow Jones", dow, group="US", why="US risk-on/off overnight bias", when="Before India open (US close already done)", src="Upstox/Yahoo"),
        _col("spx", "S&P 500", spx, group="US", why="Global equity beta", when="Pre-market", src="Upstox/Yahoo"),
        _col("nasdaq", "Nasdaq / US Tech", nasdaq, group="US", why="Tech / growth risk appetite", when="Pre-market", src="Upstox/Yahoo"),
        # Asia
        _col("nikkei", "Nikkei 225", nikkei, group="Asia", why="Japan risk; Asia open spillover", when="Early India morning", src="Upstox/Yahoo"),
        _col("hsi", "Hang Seng", hsi, group="Asia", why="China/HK risk; FII Asia flow mood", when="Early India morning", src="Upstox/Yahoo"),
        # Europe
        _col("ftse", "FTSE 100 (UK)", ftse, group="Europe", why="Europe risk; London close vs Asia open timing", when="India morning (Europe still trading / prior close)", src="Yahoo"),
        _col("dax", "DAX (Germany)", dax, group="Europe", why="Eurozone industrial risk appetite", when="India morning", src="Yahoo"),
        _col("cac", "CAC 40 (France)", cac, group="Europe", why="Eurozone confirmation with DAX", when="India morning", src="Yahoo"),
        _col("stoxx50", "EURO STOXX 50", stoxx50, group="Europe", why="Broad Europe blue-chip bias", when="India morning", src="Yahoo"),
        # Cash
        _col("fii_cash_net", "FII Cash Net ₹Cr", fii_net, group="Cash Flow", why="Foreign cash buying/selling pressure", when="Evening provisional; next morning confirmed", src="MrChartist/NSE"),
        _col("dii_cash_net", "DII Cash Net ₹Cr", dii_net, group="Cash Flow", why="Domestic absorption of FII selling", when="Same as FII cash", src="MrChartist/NSE"),
        # NSE OI — the edge
        _col(
            "fii_idx_fut_long",
            "FII Idx Fut Long",
            fut_l,
            display=fut_l_disp,
            group="FII OI (NSE)",
            why="FII long OI in index futures — bullish positioning if high + rising",
            when="Daily ~7:00–7:30 PM IST (after close)",
            src="NSE fao_participant_oi CSV",
            fmt="display",
        ),
        _col(
            "fii_idx_fut_short",
            "FII Idx Fut Short",
            fut_s,
            display=fut_s_disp,
            group="FII OI (NSE)",
            why="FII short OI — bearish / hedge. High short % = caution for longs",
            when="Daily ~7:00–7:30 PM IST",
            src="NSE CSV",
            fmt="display",
        ),
        _col(
            "fii_idx_fut_long_pct",
            "FII Long %",
            fut_l_pct,
            display=f"{fut_l_pct:.2f}%" if fut_l_pct is not None else None,
            group="FII OI (NSE)",
            why="Share of FII index-fut OI that is long",
            when="With OI report",
            src="computed",
            fmt="pct_points",
        ),
        _col(
            "fii_idx_fut_short_pct",
            "FII Short %",
            fut_s_pct,
            display=f"{fut_s_pct:.2f}%" if fut_s_pct is not None else None,
            group="FII OI (NSE)",
            why="Share that is short — 90%+ short often extreme hedge/bearish",
            when="With OI report",
            src="computed",
            fmt="pct_points",
        ),
        _col("fii_idx_fut_net", "FII Idx Fut Net (L−S)", fut_net, group="FII OI (NSE)", why="Net directional futures bias", when="With OI report", src="computed"),
        _col("fii_idx_fut_ratio", "FII Long/Short Ratio", fut_ratio, group="FII OI (NSE)", why=">1 net long, <1 net short — real edge most miss", when="With OI report", src="computed"),
        _col(
            "fii_idx_opt_pcr_short",
            "FII Idx Opt PCR (short OI)",
            fii_pcr_oi,
            group="FII OI (NSE)",
            why="Put short / Call short on FII index options",
            when="With OI report",
            src="NSE CSV",
        ),
        _col("pcr", "PCR (sentiment API)", pcr, group="Sentiment", why="Quick put-call sentiment", when="Evening / next day", src="MrChartist"),
        _col("sentiment", "Sentiment Score", sentiment, group="Sentiment", why="0–100 quick bias score", when="With cash/OI feed", src="MrChartist"),
        _col("oi_date", "OI Report Date", oi_date, group="Meta", why="Which session OI belongs to", when="After 7–7:30 PM", src="NSE", fmt="text"),
        _col("last_updated", "Last Updated", now_str(), group="Meta", why="Freshness", when="Every refresh", src="script", fmt="text"),
    ]

    # Flat row for daily log (column-wise keys)
    row: dict[str, Any] = {
        "date": ymd,
        "day": trading["day"],
        "is_trading": trading["is_trading"],
        "holiday": trading["holiday"],
        "nifty": nifty,
        "banknifty": bank,
        "vix": vix,
        "gift": gift,
        "gap_pts": gap_pts,
        "gap_pct": gap_pct,
        "gap_category": gap_cat,
        "dow": dow,
        "spx": spx,
        "nasdaq": nasdaq,
        "nikkei": nikkei,
        "hsi": hsi,
        "ftse": ftse,
        "dax": dax,
        "cac": cac,
        "stoxx50": stoxx50,
        "fii_cash_net": fii_net,
        "dii_cash_net": dii_net,
        "fii_idx_fut_long": fut_l,
        "fii_idx_fut_short": fut_s,
        "fii_idx_fut_long_pct": fut_l_pct,
        "fii_idx_fut_short_pct": fut_s_pct,
        "fii_idx_fut_long_display": fut_l_disp,
        "fii_idx_fut_short_display": fut_s_disp,
        "fii_idx_fut_net": fut_net,
        "fii_idx_fut_ratio": fut_ratio,
        "fii_idx_opt_pcr_short": fii_pcr_oi,
        "dii_idx_fut_long_display": nse_oi.get("dii_idx_fut_long_display"),
        "dii_idx_fut_short_display": nse_oi.get("dii_idx_fut_short_display"),
        "pcr": pcr,
        "sentiment": sentiment,
        "oi_date": oi_date,
        "fii_session_date": fii_date,
        "api_updated": api_updated,
        "last_updated": now_str(),
        "sources": sources,
        "errors": errors,
        "upstox_enabled": upstox_enabled(),
        "nse_oi_url": nse_oi.get("source_url"),
        "nse_participants": nse_oi.get("participants"),
    }

    # Ensure all DAILY_COLUMNS present
    for c in DAILY_COLUMNS:
        row.setdefault(c, None)

    snapshot = {
        **row,
        "columns": columns,
        "column_groups": _group_columns(columns),
        "schema": DAILY_COLUMNS,
    }

    # ── FII-only 1-week OI trend + next-day match (no DII/Pro/Client in this view)
    fii_week: dict[str, Any] = {}
    try:
        fii_week = build_week_trend(lookback=8)
        sources.append("fii_week_trend")
    except Exception as e:
        errors.append(f"fii_week:{e}")
        log.exception("fii_week")

    snapshot["fii_week"] = fii_week
    snapshot["sources"] = sources
    snapshot["errors"] = errors

    storage.save_latest(snapshot)
    # history without huge nested participants every day? keep slim
    hist = {k: row[k] for k in DAILY_COLUMNS if k in row}
    hist["errors"] = errors
    storage.upsert_daily(hist)
    return snapshot


def _group_columns(columns: list[dict]) -> list[dict]:
    order = ["Meta", "India", "Gap", "US", "Asia", "Europe", "Cash Flow", "FII OI (NSE)", "Sentiment"]
    buckets: dict[str, list] = {}
    for c in columns:
        buckets.setdefault(c.get("group") or "Other", []).append(c)
    out = []
    for g in order:
        if g in buckets:
            out.append({"group": g, "columns": buckets[g]})
    for g, cols in buckets.items():
        if g not in order:
            out.append({"group": g, "columns": cols})
    return out
