"""
Pre-market board helpers:

1) Expected gap = GIFT − Nifty **previous session close** (NOT live Nifty).
2) Freeze pre-market fields after 09:15 IST so gap/GIFT/globals don't drift all day.
3) Europe → Nifty influence windows + daily match log.

Europe timing (IST, approximate; DST shifts ±1h):
  • 12:30 — EU cash open (Frankfurt/Paris ~08:00 CET → ~12:30 IST summer)
  • 13:30 — London open pulse (08:00 UK winter → 13:30 IST; summer 12:30)
  • 14:30 — late overlap into India close

Literature / desk practice (not a hard law):
  • Overnight open gap: dominated by US + GIFT (~strong lead).
  • Midday Nifty direction with Europe: **moderate** co-move —
    rough historical directional agreement ~50–60% in EU overlap
    (weaker than US overnight). We use **~55%** as reference prior
    and log *today* match/miss so you build your own sample.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import DATA_DIR, GAP_MEDIUM_PCT, GAP_SMALL_PCT

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")

LOCK_FILE = DATA_DIR / "premarket_lock.json"
EUROPE_FILE = DATA_DIR / "europe_track.json"

# Reference: typical directional influence of Europe on Nifty during overlap
EUROPE_INFLUENCE_PRIOR_PCT = 55

# Windows to sample (start_min from midnight IST, duration_min)
EUROPE_WINDOWS = (
    {
        "id": "eu_open",
        "label": "Europe open (DAX/CAC/FTSE)",
        "hhmm": "12:30",
        "start_min": 12 * 60 + 25,
        "end_min": 12 * 60 + 55,
        "note": "EU cash open pulse — moderate Nifty risk tone",
    },
    {
        "id": "london_pulse",
        "label": "London / EU consolidate",
        "hhmm": "13:30",
        "start_min": 13 * 60 + 25,
        "end_min": 13 * 60 + 55,
        "note": "London open (winter) / EU follow-through",
    },
    {
        "id": "eu_late",
        "label": "Late Europe → India close",
        "hhmm": "14:30",
        "start_min": 14 * 60 + 25,
        "end_min": 15 * 60 + 5,
        "note": "Peak overlap — Nifty often echoes EU risk into close",
    },
)

# Pre fields that freeze after open (live India prices stay free for Live tab)
FREEZE_KEYS = (
    "gift",
    "gift_display",
    "gift_chg_pct",
    "nifty_prev_close",
    "nifty_prev_display",
    "gap_pts",
    "gap_pct",
    "gap_category",
    "gap_display",
    "gap_formula",
    "dow",
    "dow_display",
    "dow_chg_pct",
    "spx",
    "spx_display",
    "spx_chg_pct",
    "nasdaq",
    "nasdaq_display",
    "nasdaq_chg_pct",
    "nikkei",
    "nikkei_display",
    "nikkei_chg_pct",
    "hsi",
    "hsi_display",
    "hsi_chg_pct",
    "ftse",
    "ftse_display",
    "ftse_chg_pct",
    "dax",
    "dax_display",
    "dax_chg_pct",
    "cac",
    "cac_display",
    "cac_chg_pct",
    "stoxx50",
    "stoxx50_display",
    "stoxx50_chg_pct",
    "fii_cash_net",
    "dii_cash_net",
    "pre_headline",
    "pre_plan",
)


def now_ist() -> datetime:
    return datetime.now(TZ)


def _mins(dt: datetime | None = None) -> int:
    d = dt or now_ist()
    return d.hour * 60 + d.minute


def market_open_mins() -> int:
    return 9 * 60 + 15  # 09:15


def is_pre_session(dt: datetime | None = None) -> bool:
    """True before 09:15 IST (pre-market update window)."""
    return _mins(dt) < market_open_mins()


def gap_category(gap_pct: float | None) -> str:
    if gap_pct is None:
        return ""
    # accept fraction (0.003) or percent (0.3)
    pct = abs(float(gap_pct))
    if pct < 1:  # fraction
        pct *= 100.0
    if pct < GAP_SMALL_PCT:
        return "Small"
    if pct < GAP_MEDIUM_PCT:
        return "Medium"
    return "Large"


def compute_expected_gap(
    gift: float | None,
    nifty_prev_close: float | None,
) -> dict[str, Any]:
    """
    Expected open gap in points/% using overnight lead:
      gap_pts = GIFT − Nifty previous close
    """
    out: dict[str, Any] = {
        "gap_pts": None,
        "gap_pct": None,
        "gap_category": "",
        "gap_display": "—",
        "gap_formula": "GIFT − Nifty prev close",
        "nifty_prev_close": nifty_prev_close,
        "gift": gift,
        "bias": "UNKNOWN",
    }
    if gift is None or nifty_prev_close in (None, 0):
        return out
    pts = float(gift) - float(nifty_prev_close)
    pct_frac = pts / float(nifty_prev_close)
    cat = gap_category(pct_frac)
    sign = "+" if pts > 0 else ""
    out.update(
        {
            "gap_pts": round(pts, 2),
            "gap_pct": round(pct_frac, 6),
            "gap_category": cat,
            "gap_display": f"{sign}{pts:,.1f} pts ({sign}{pct_frac * 100:.2f}%)",
            "bias": "GAP UP" if pts > 8 else ("GAP DOWN" if pts < -8 else "FLAT / SMALL"),
        }
    )
    return out


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning("read %s: %s", path, e)
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_lock() -> dict:
    return _read_json(LOCK_FILE)


def save_lock(data: dict) -> None:
    _write_json(LOCK_FILE, data)


def freeze_or_update_pre(ymd: str, live_pre: dict[str, Any], is_trading: bool) -> dict[str, Any]:
    """
    Before 09:15: keep refreshing pre board from live_pre.
    At/after 09:15 on a trading day: freeze once for the day (don't change gap/GIFT overnight set).
    """
    all_locks = load_lock()
    existing = all_locks.get(ymd) if isinstance(all_locks.get(ymd), dict) else None
    now = now_ist()
    pre_time = is_pre_session(now)

    if existing and existing.get("frozen") and is_trading:
        # Stay frozen all day
        existing["status"] = "FROZEN"
        existing["status_note"] = (
            f"Locked at {existing.get('frozen_at', '—')} — pre numbers don't change after open"
        )
        return existing

    # Prefer last pre-session snapshot when locking after open (don't use post-open drift)
    if (
        is_trading
        and not pre_time
        and existing
        and not existing.get("frozen")
        and existing.get("status") == "LIVE PRE"
    ):
        payload = dict(existing)
        payload["frozen"] = True
        payload["frozen_at"] = now.strftime("%Y-%m-%d %H:%M:%S IST")
        payload["status"] = "FROZEN"
        payload["status_note"] = (
            "Locked last pre-09:15 print. Gap/GIFT/US/Asia overnight fixed for today."
        )
        payload["updated_at"] = payload["frozen_at"]
    else:
        payload = {k: live_pre.get(k) for k in FREEZE_KEYS if k in live_pre}
        for k, v in live_pre.items():
            if k not in payload:
                payload[k] = v

        payload["date"] = ymd
        payload["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S IST")

        if is_trading and not pre_time:
            # No pre print stored (server started after open) → freeze current correct gap formula
            payload["frozen"] = True
            payload["frozen_at"] = payload["updated_at"]
            payload["status"] = "FROZEN"
            payload["status_note"] = (
                "Pre-market locked after 09:15 (no earlier pre print). "
                "Gap still = GIFT − Nifty prev close at lock time."
            )
        else:
            payload["frozen"] = False
            payload["status"] = "LIVE PRE"
            payload["status_note"] = (
                "Pre-market window — GIFT & gap updating until 09:15 IST open."
                if is_trading
                else "Non-trading day — numbers informational only."
            )

    all_locks[ymd] = payload
    # prune old locks (keep 30 days)
    if len(all_locks) > 40:
        keys = sorted(k for k in all_locks if k[:4].isdigit())
        for k in keys[:-30]:
            all_locks.pop(k, None)
    save_lock(all_locks)
    return payload


def apply_freeze_to_snapshot(snapshot: dict, locked: dict) -> dict:
    """Overlay frozen pre fields onto snapshot for Pre tab consistency."""
    if not locked:
        return snapshot
    for k in FREEZE_KEYS:
        if k in locked and locked[k] is not None:
            snapshot[k] = locked[k]
    snapshot["pre_status"] = locked.get("status")
    snapshot["pre_status_note"] = locked.get("status_note")
    snapshot["pre_frozen"] = bool(locked.get("frozen"))
    snapshot["pre_frozen_at"] = locked.get("frozen_at")
    snapshot["pre_updated_at"] = locked.get("updated_at")
    # keep gap aliases used by UI
    if locked.get("gap_pts") is not None:
        snapshot["gap_pts"] = locked["gap_pts"]
    if locked.get("gap_pct") is not None:
        snapshot["gap_pct"] = locked["gap_pct"]
    if locked.get("gap_category"):
        snapshot["gap_category"] = locked["gap_category"]
    if locked.get("gift") is not None:
        snapshot["gift"] = locked["gift"]
    if locked.get("gift_display"):
        snapshot["gift_display"] = locked["gift_display"]
    return snapshot


def _eu_bias_from_chgs(chgs: list[float | None]) -> tuple[str, float | None]:
    vals = [float(c) for c in chgs if c is not None]
    if not vals:
        return "FLAT", None
    avg = sum(vals) / len(vals)
    if avg > 0.08:
        return "UP", round(avg, 3)
    if avg < -0.08:
        return "DOWN", round(avg, 3)
    return "FLAT", round(avg, 3)


def load_europe_track() -> dict:
    return _read_json(EUROPE_FILE)


def save_europe_track(data: dict) -> None:
    _write_json(EUROPE_FILE, data)


def update_europe_track(
    ymd: str,
    *,
    nifty: float | None,
    ftse_chg: float | None,
    dax_chg: float | None,
    cac_chg: float | None,
    stoxx_chg: float | None,
    is_trading: bool,
) -> dict[str, Any]:
    """
    Sample Europe windows; when window ends, score match vs Nifty move.
    Returns today's europe board for UI.
    """
    store = load_europe_track()
    day = store.get(ymd) if isinstance(store.get(ymd), dict) else None
    if not day:
        day = {
            "date": ymd,
            "prior_influence_pct": EUROPE_INFLUENCE_PRIOR_PCT,
            "prior_note": (
                "Europe–Nifty midday co-move is moderate (~50–60% same-direction days in "
                "overlap studies/desk practice). Weaker than US overnight/GIFT for the open. "
                "Log builds your personal hit-rate."
            ),
            "windows": {},
            "summary": {},
        }

    now = now_ist()
    mins = _mins(now)
    eu_bias, eu_avg = _eu_bias_from_chgs([ftse_chg, dax_chg, cac_chg, stoxx_chg])

    windows_out = day.get("windows") or {}
    for w in EUROPE_WINDOWS:
        wid = w["id"]
        slot = windows_out.get(wid) or {
            "id": wid,
            "label": w["label"],
            "hhmm": w["hhmm"],
            "note": w["note"],
            "status": "WAITING",
            "match": None,
        }

        in_window = w["start_min"] <= mins <= w["end_min"]
        after_window = mins > w["end_min"]

        if is_trading and in_window:
            if slot.get("nifty_start") is None and nifty is not None:
                slot["nifty_start"] = nifty
                slot["started_at"] = now.strftime("%H:%M")
            slot["status"] = "SAMPLING"
            slot["eu_bias"] = eu_bias
            slot["eu_avg_chg_pct"] = eu_avg
            slot["ftse_chg_pct"] = ftse_chg
            slot["dax_chg_pct"] = dax_chg
            slot["cac_chg_pct"] = cac_chg
            slot["last_sample_at"] = now.strftime("%H:%M:%S")
            if nifty is not None:
                slot["nifty_last"] = nifty

        if is_trading and after_window and slot.get("status") in ("SAMPLING", "WAITING"):
            # close the window — prefer latest Nifty print at close time
            start = slot.get("nifty_start")
            end = nifty if nifty is not None else slot.get("nifty_last")
            if start is not None and end is not None:
                move = float(end) - float(start)
                slot["nifty_end"] = end
                slot["nifty_move_pts"] = round(move, 2)
                if move > 8:
                    n_bias = "UP"
                elif move < -8:
                    n_bias = "DOWN"
                else:
                    n_bias = "FLAT"
                slot["nifty_bias"] = n_bias
                eb = slot.get("eu_bias") or eu_bias
                if eb == "FLAT" or n_bias == "FLAT":
                    slot["match"] = None
                    slot["match_label"] = "NEUTRAL / flat — no call"
                elif eb == n_bias:
                    slot["match"] = True
                    slot["match_label"] = "MATCH — Nifty followed Europe"
                else:
                    slot["match"] = False
                    slot["match_label"] = "MISS — Nifty diverged from Europe"
                slot["status"] = "DONE"
                slot["closed_at"] = now.strftime("%H:%M")
            elif after_window and mins > w["end_min"] + 15:
                slot["status"] = "SKIPPED"
                slot["match_label"] = "No Nifty sample in window"
                slot["match"] = None

        # waiting state before window
        if mins < w["start_min"] and slot.get("status") not in ("DONE", "SKIPPED", "SAMPLING"):
            slot["status"] = "WAITING"
            slot["eu_bias"] = eu_bias  # show current EU tone early
            slot["eu_avg_chg_pct"] = eu_avg

        windows_out[wid] = slot

    day["windows"] = windows_out

    # summary hit rate today
    done = [s for s in windows_out.values() if s.get("match") is not None]
    hits = sum(1 for s in done if s.get("match") is True)
    day["summary"] = {
        "windows_scored": len(done),
        "matches": hits,
        "misses": sum(1 for s in done if s.get("match") is False),
        "hit_rate_pct": round(100.0 * hits / len(done), 1) if done else None,
        "prior_pct": EUROPE_INFLUENCE_PRIOR_PCT,
        "eu_bias_now": eu_bias,
        "eu_avg_chg_pct": eu_avg,
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S IST"),
    }
    day["influence_guide"] = {
        "open_gap": "US close + GIFT dominate Nifty open (strongest)",
        "midday": f"Europe moderate ~{EUROPE_INFLUENCE_PRIOR_PCT}% same-direction prior",
        "times_ist": [w["hhmm"] + " " + w["label"] for w in EUROPE_WINDOWS],
    }

    store[ymd] = day
    save_europe_track(store)

    # UI-friendly list
    ordered = [windows_out[w["id"]] for w in EUROPE_WINDOWS if w["id"] in windows_out]
    return {
        "date": ymd,
        "prior_influence_pct": EUROPE_INFLUENCE_PRIOR_PCT,
        "prior_note": day.get("prior_note"),
        "windows": ordered,
        "summary": day["summary"],
        "influence_guide": day["influence_guide"],
    }


def pre_headline_from_gap(gap: dict, fii_bias: str | None = None) -> tuple[str, str]:
    bias = gap.get("bias") or "UNKNOWN"
    disp = gap.get("gap_display") or "—"
    cat = gap.get("gap_category") or ""
    head = f"Open plan: {bias}"
    if cat:
        head += f" · {cat} gap"
    plan = f"Expected {disp} (GIFT vs Nifty prev close)."
    if bias == "GAP UP":
        plan += " Bias: buy dips in first 30–45m if holds above open; avoid panic shorts."
    elif bias == "GAP DOWN":
        plan += " Bias: sell rips / wait for reclaim; watch gap-fill to prev close."
    else:
        plan += " Flat open — ORB + OI walls decide; 25–35 pt scalps inside range."
    if fii_bias:
        plan += f" FII: {fii_bias}."
    return head, plan
