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
    format_price_chg,
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
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        v = yahoo.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    def pick_chg_pct(key: str) -> float | None:
        """Prefer a non-null, non-bogus day change. Yahoo candle math is reliable."""
        candidates: list[float] = []
        for src in (yahoo, upstox):  # Yahoo first for % accuracy
            v = src.get(f"{key}_chg_pct")
            if v is None:
                continue
            try:
                candidates.append(float(v))
            except (TypeError, ValueError):
                pass
        if not candidates:
            return None
        # Prefer first non-zero if any non-zero exists (avoid 0.00% from bad prev)
        for c in candidates:
            if abs(c) > 1e-9:
                return c
        return candidates[0]

    def pick_display(key: str) -> str | None:
        """Build display from best price + best day % (never stick with fake 0.00%)."""
        price = pick(key)
        chg = pick_chg_pct(key)
        built = format_price_chg(price, chg)
        if built:
            return built
        for src in (yahoo, upstox):
            d = src.get(f"{key}_display")
            if d and "(0.00%)" not in str(d):
                return str(d)
        for src in (yahoo, upstox):
            d = src.get(f"{key}_display")
            if d:
                return str(d)
        return None

    def px(key: str) -> tuple[float | None, float | None, str | None]:
        return pick(key), pick_chg_pct(key), pick_display(key)

    nifty, nifty_chg, nifty_d = px("nifty")
    bank, bank_chg, bank_d = px("banknifty")
    sensex, sensex_chg, sensex_d = px("sensex")
    vix, vix_chg, vix_d = px("vix")
    gift, gift_chg, gift_d = px("gift")
    dow, dow_chg, dow_d = px("dow")
    spx, spx_chg, spx_d = px("spx")
    nasdaq, nasdaq_chg, nasdaq_d = px("nasdaq")
    nikkei, nikkei_chg, nikkei_d = px("nikkei")
    hsi, hsi_chg, hsi_d = px("hsi")
    ftse, ftse_chg, ftse_d = px("ftse")
    dax, dax_chg, dax_d = px("dax")
    cac, cac_chg, cac_d = px("cac")
    stoxx50, stoxx50_chg, stoxx50_d = px("stoxx50")

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
    gap_pts_d = gap_pct_d = None
    if gift is not None and nifty is not None and nifty != 0:
        gap_pts = gift - nifty
        gap_pct = gap_pts / nifty
        gap_cat = gap_category(gap_pct)
        sign = "+" if gap_pts > 0 else ""
        gap_pts_d = f"{gap_pts:,.2f} ({sign}{gap_pct * 100:.2f}%)"
        gap_pct_d = f"{sign}{gap_pct * 100:.2f}%"

    # FII/DII cash: day-over-day change % vs previous stored session
    fii_d = dii_d = None
    try:
        hist = storage.load_daily()
        prev_fii = prev_dii = None
        for h in hist:
            if h.get("date") and h.get("date") != ymd:
                if h.get("fii_cash_net") is not None and prev_fii is None:
                    prev_fii = h.get("fii_cash_net")
                if h.get("dii_cash_net") is not None and prev_dii is None:
                    prev_dii = h.get("dii_cash_net")
                if prev_fii is not None and prev_dii is not None:
                    break
        if fii_net is not None:
            if prev_fii not in (None, 0):
                fii_chg = 100.0 * (float(fii_net) - float(prev_fii)) / abs(float(prev_fii))
                sign = "+" if fii_net > 0 else ""
                fii_d = f"{sign}{float(fii_net):,.2f} ({'+' if fii_chg > 0 else ''}{fii_chg:.1f}% vs prev)"
            else:
                sign = "+" if fii_net > 0 else ""
                fii_d = f"{sign}{float(fii_net):,.2f}"
        if dii_net is not None:
            if prev_dii not in (None, 0):
                dii_chg = 100.0 * (float(dii_net) - float(prev_dii)) / abs(float(prev_dii))
                sign = "+" if dii_net > 0 else ""
                dii_d = f"{sign}{float(dii_net):,.2f} ({'+' if dii_chg > 0 else ''}{dii_chg:.1f}% vs prev)"
            else:
                sign = "+" if dii_net > 0 else ""
                dii_d = f"{sign}{float(dii_net):,.2f}"
    except Exception:
        if fii_net is not None:
            fii_d = f"{float(fii_net):,.2f}"
        if dii_net is not None:
            dii_d = f"{float(dii_net):,.2f}"

    def _idx_col(key, label, val, chg, disp, group, why, when, src="Upstox/Yahoo"):
        return _col(
            key, label, val,
            display=disp or format_price_chg(val, chg),
            group=group, why=why, when=when, src=src, fmt="display",
        )

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
        # India — value (day chg %)
        _idx_col("nifty", "Nifty 50 Close", nifty, nifty_chg, nifty_d, "India", "Base for gap + trend reference", "Pre-market + close"),
        _idx_col("banknifty", "BankNifty Close", bank, bank_chg, bank_d, "India", "Bank-heavy days / which index to trade", "Pre-market + close"),
        _idx_col("sensex", "Sensex (BSE)", sensex, sensex_chg, sensex_d, "India", "BSE broad market; confirm Nifty bias", "Pre-market + close"),
        _idx_col("vix", "India VIX", vix, vix_chg, vix_d, "India", "Low=range day, High=big moves / premium", "Pre-market; spikes on events"),
        # GIFT + Gap
        _idx_col("gift", "GIFT Nifty", gift, gift_chg, gift_d, "Gap", "Strongest overnight lead for Nifty open", "Pre-market (early morning)", "Upstox GLOBAL"),
        _col("gap_pts", "Expected Gap Pts", gap_pts, display=gap_pts_d, group="Gap", why="Open expectation in points (+ % of Nifty)", when="Pre-market after GIFT", src="GIFT−Nifty", fmt="display"),
        _col(
            "gap_pct",
            "Expected Gap %",
            gap_pct,
            display=gap_pct_d,
            group="Gap",
            why="ORB / gap-fill rules",
            when="Pre-market",
            src="formula",
            fmt="display",
        ),
        _col("gap_category", "Gap Category", gap_cat, group="Gap", why="Small/Med/Large → different ORB plan", when="Pre-market", src="formula", fmt="text"),
        # US
        _idx_col("dow", "Dow Jones", dow, dow_chg, dow_d, "US", "US risk-on/off overnight bias", "Before India open (US close already done)"),
        _idx_col("spx", "S&P 500", spx, spx_chg, spx_d, "US", "Global equity beta", "Pre-market"),
        _idx_col("nasdaq", "Nasdaq / US Tech", nasdaq, nasdaq_chg, nasdaq_d, "US", "Tech / growth risk appetite", "Pre-market"),
        # Asia
        _idx_col("nikkei", "Nikkei 225", nikkei, nikkei_chg, nikkei_d, "Asia", "Japan risk; Asia open spillover", "Early India morning"),
        _idx_col("hsi", "Hang Seng", hsi, hsi_chg, hsi_d, "Asia", "China/HK risk; FII Asia flow mood", "Early India morning"),
        # Europe
        _idx_col("ftse", "FTSE 100 (UK)", ftse, ftse_chg, ftse_d, "Europe", "Europe risk; London close vs Asia open timing", "India morning", "Yahoo"),
        _idx_col("dax", "DAX (Germany)", dax, dax_chg, dax_d, "Europe", "Eurozone industrial risk appetite", "India morning", "Yahoo"),
        _idx_col("cac", "CAC 40 (France)", cac, cac_chg, cac_d, "Europe", "Eurozone confirmation with DAX", "India morning", "Yahoo"),
        _idx_col("stoxx50", "EURO STOXX 50", stoxx50, stoxx50_chg, stoxx50_d, "Europe", "Broad Europe blue-chip bias", "India morning", "Yahoo"),
        # Cash
        _col("fii_cash_net", "FII Cash Net ₹Cr", fii_net, display=fii_d, group="Cash Flow", why="Foreign cash buying/selling pressure", when="Evening provisional; next morning confirmed", src="MrChartist/NSE", fmt="display"),
        _col("dii_cash_net", "DII Cash Net ₹Cr", dii_net, display=dii_d, group="Cash Flow", why="Domestic absorption of FII selling", when="Same as FII cash", src="MrChartist/NSE", fmt="display"),
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
        "nifty_chg_pct": nifty_chg,
        "nifty_display": nifty_d,
        "banknifty": bank,
        "banknifty_chg_pct": bank_chg,
        "banknifty_display": bank_d,
        "sensex": sensex,
        "sensex_chg_pct": sensex_chg,
        "sensex_display": sensex_d,
        "vix": vix,
        "vix_chg_pct": vix_chg,
        "vix_display": vix_d,
        "gift": gift,
        "gift_chg_pct": gift_chg,
        "gift_display": gift_d,
        "gap_pts": gap_pts,
        "gap_pct": gap_pct,
        "gap_category": gap_cat,
        "dow": dow,
        "dow_chg_pct": dow_chg,
        "dow_display": dow_d,
        "spx": spx,
        "spx_chg_pct": spx_chg,
        "spx_display": spx_d,
        "nasdaq": nasdaq,
        "nasdaq_chg_pct": nasdaq_chg,
        "nasdaq_display": nasdaq_d,
        "nikkei": nikkei,
        "nikkei_chg_pct": nikkei_chg,
        "nikkei_display": nikkei_d,
        "hsi": hsi,
        "hsi_chg_pct": hsi_chg,
        "hsi_display": hsi_d,
        "ftse": ftse,
        "ftse_chg_pct": ftse_chg,
        "ftse_display": ftse_d,
        "dax": dax,
        "dax_chg_pct": dax_chg,
        "dax_display": dax_d,
        "cac": cac,
        "cac_chg_pct": cac_chg,
        "cac_display": cac_d,
        "stoxx50": stoxx50,
        "stoxx50_chg_pct": stoxx50_chg,
        "stoxx50_display": stoxx50_d,
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
