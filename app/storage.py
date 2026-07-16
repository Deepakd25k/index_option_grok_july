"""Local JSON storage — free, no cloud bill.

Strategy:
  • daily_history.json  — last DAILY_RETENTION_DAYS trading snapshots
  • weekly_history.json — rolled-up week averages for older data
  • latest.json         — always the newest full snapshot for the UI
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import (
    DAILY_FILE,
    DAILY_RETENTION_DAYS,
    SNAPSHOT_FILE,
    WEEKLY_FILE,
    WEEKLY_RETENTION_WEEKS,
)

log = logging.getLogger(__name__)


def _read(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("read %s: %s", path, e)
        return None


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def save_latest(snapshot: dict) -> None:
    _write(SNAPSHOT_FILE, snapshot)


def load_latest() -> dict | None:
    data = _read(SNAPSHOT_FILE)
    return data if isinstance(data, dict) else None


def load_daily() -> list[dict]:
    data = _read(DAILY_FILE)
    return data if isinstance(data, list) else []


def load_weekly() -> list[dict]:
    data = _read(WEEKLY_FILE)
    return data if isinstance(data, list) else []


def upsert_daily(row: dict) -> list[dict]:
    """Insert/update by date, prune old, roll into weekly."""
    rows = load_daily()
    ymd = row.get("date")
    found = False
    for i, r in enumerate(rows):
        if r.get("date") == ymd:
            rows[i] = {**r, **row}
            found = True
            break
    if not found:
        rows.append(row)

    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    rows = _prune_and_roll(rows)
    _write(DAILY_FILE, rows)
    return rows


def _week_key(ymd: str) -> str:
    d = date.fromisoformat(ymd)
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _avg(vals: list[float | None]) -> float | None:
    nums = [v for v in vals if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _prune_and_roll(daily: list[dict]) -> list[dict]:
    cutoff = (date.today() - timedelta(days=DAILY_RETENTION_DAYS)).isoformat()
    keep: list[dict] = []
    roll: list[dict] = []
    for r in daily:
        d = r.get("date") or ""
        if d >= cutoff:
            keep.append(r)
        else:
            roll.append(r)

    if roll:
        weekly = load_weekly()
        buckets: dict[str, list[dict]] = {}
        for r in roll:
            wk = _week_key(r["date"])
            buckets.setdefault(wk, []).append(r)

        existing = {w.get("week"): w for w in weekly}
        for wk, items in buckets.items():
            fields = [
                "nifty", "banknifty", "sensex", "vix", "gift", "dow", "spx", "nasdaq",
                "nikkei", "hsi", "fii_net", "dii_net", "pcr", "sentiment",
                "gap_pct",
            ]
            agg: dict[str, Any] = {
                "week": wk,
                "from": min(i["date"] for i in items),
                "to": max(i["date"] for i in items),
                "sessions": len(items),
                "type": "weekly_rollup",
            }
            for f in fields:
                agg[f] = _avg([i.get(f) for i in items])
            existing[wk] = {**existing.get(wk, {}), **agg}

        weekly = sorted(existing.values(), key=lambda w: w.get("week") or "", reverse=True)
        # prune weeks
        if len(weekly) > WEEKLY_RETENTION_WEEKS:
            weekly = weekly[:WEEKLY_RETENTION_WEEKS]
        _write(WEEKLY_FILE, weekly)
        log.info("Rolled %s daily rows into weekly; kept %s daily", len(roll), len(keep))

    return keep


def history_for_ui(limit: int = 60) -> dict:
    return {
        "daily": load_daily()[:limit],
        "weekly": load_weekly()[:52],
        "retention": {
            "daily_days": DAILY_RETENTION_DAYS,
            "weekly_weeks": WEEKLY_RETENTION_WEEKS,
            "note": "Local JSON only — no Google, no cloud bill",
        },
    }
