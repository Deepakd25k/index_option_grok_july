"""NSE India F&O Participant-wise Open Interest (daily ~7:00–7:30 PM IST).

Official CSV:
  https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv

Columns include FII/DII/Client/Pro × Index Futures Long/Short, Options, etc.
We compute percentages so UI can show:  26357 (8.4%)
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Kolkata")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/octet-stream,*/*",
    "Referer": "https://www.nseindia.com/all-reports-derivatives",
}

BASE_URLS = [
    "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv",
    "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv",
]


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d%m%Y")


def _pct(part: float, total: float) -> float | None:
    if total is None or total == 0:
        return None
    return round(100.0 * part / total, 2)


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def format_with_pct(value: float | None, pct: float | None) -> str | None:
    """26357 (8.36%) style display string."""
    if value is None:
        return None
    if pct is None:
        return f"{int(value):,}"
    return f"{int(value):,} ({pct:.2f}%)"


def parse_participant_csv(text: str) -> dict[str, dict[str, float]]:
    """Return {CLIENT_TYPE: {field: number}} for Client/DII/FII/Pro/TOTAL."""
    lines = text.splitlines()
    # skip title row(s) until header with Client Type
    start = 0
    for i, line in enumerate(lines):
        if "Client Type" in line or line.startswith("Client Type"):
            start = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    # normalize headers (strip spaces)
    out: dict[str, dict[str, float]] = {}
    for row in reader:
        # first key may have BOM / quotes
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            nk = k.strip().strip('"').replace("  ", " ")
            cleaned[nk] = v
        ctype = (cleaned.get("Client Type") or "").strip()
        if not ctype:
            continue
        # map all numeric fields
        fields = {}
        for k, v in cleaned.items():
            if k == "Client Type":
                continue
            n = _num(v)
            if n is not None:
                # normalize key names
                key = (
                    k.strip()
                    .lower()
                    .replace(" ", "_")
                    .replace("\t", "")
                )
                fields[key] = n
        out[ctype.upper()] = fields
    return out


def enrich_participant(fields: dict[str, float]) -> dict[str, Any]:
    """Add ratio + long/short % for index futures & totals."""
    fl = fields.get("future_index_long")
    fs = fields.get("future_index_short")
    total_ls = (fl or 0) + (fs or 0)

    long_pct = _pct(fl or 0, total_ls) if fl is not None else None
    short_pct = _pct(fs or 0, total_ls) if fs is not None else None
    ratio = (fl / fs) if (fl is not None and fs) else None
    net = (fl - fs) if (fl is not None and fs is not None) else None

    # Index options PCR on short OI (put short / call short) — classic
    call_s = fields.get("option_index_call_short")
    put_s = fields.get("option_index_put_short")
    pcr_short = (put_s / call_s) if (put_s is not None and call_s) else None

    call_l = fields.get("option_index_call_long")
    put_l = fields.get("option_index_put_long")
    pcr_long = (put_l / call_l) if (put_l is not None and call_l) else None

    tl = fields.get("total_long_contracts")
    ts = fields.get("total_short_contracts")
    total_all = (tl or 0) + (ts or 0)

    return {
        **fields,
        "idx_fut_long": fl,
        "idx_fut_short": fs,
        "idx_fut_long_pct": long_pct,
        "idx_fut_short_pct": short_pct,
        "idx_fut_net": net,
        "idx_fut_ratio": round(ratio, 4) if ratio is not None else None,
        "idx_fut_long_display": format_with_pct(fl, long_pct),
        "idx_fut_short_display": format_with_pct(fs, short_pct),
        "idx_opt_pcr_short": round(pcr_short, 4) if pcr_short is not None else None,
        "idx_opt_pcr_long": round(pcr_long, 4) if pcr_long is not None else None,
        "total_long": tl,
        "total_short": ts,
        "total_long_pct": _pct(tl or 0, total_all) if tl is not None else None,
        "total_short_pct": _pct(ts or 0, total_all) if ts is not None else None,
        "total_long_display": format_with_pct(tl, _pct(tl or 0, total_all) if tl is not None else None),
        "total_short_display": format_with_pct(ts, _pct(ts or 0, total_all) if ts is not None else None),
    }


def download_oi_for_date(d: date) -> tuple[str, str] | None:
    """Return (csv_text, ymd) or None."""
    code = _ddmmyyyy(d)
    for tmpl in BASE_URLS:
        url = tmpl.format(ddmmyyyy=code)
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code != 200:
                continue
            text = r.text
            if "Future Index Long" not in text and "Client Type" not in text:
                continue
            return text, d.isoformat()
        except Exception as e:
            log.warning("NSE OI %s: %s", url, e)
    return None


def fetch_latest_participant_oi(lookback_days: int = 7) -> dict[str, Any] | None:
    """
    Try today, then previous calendar days (skip weekends automatically by retry).
    Report usually posts ~19:00–19:30 IST for the session just closed.
    """
    today = datetime.now(TZ).date()
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:  # Sat/Sun — file usually absent
            continue
        got = download_oi_for_date(d)
        if not got:
            continue
        text, ymd = got
        try:
            raw = parse_participant_csv(text)
        except Exception as e:
            log.warning("parse OI %s: %s", ymd, e)
            continue
        if "FII" not in raw:
            continue

        participants = {k: enrich_participant(v) for k, v in raw.items()}
        fii = participants.get("FII", {})
        dii = participants.get("DII", {})
        client = participants.get("CLIENT", {})
        pro = participants.get("PRO", {})

        return {
            "oi_date": ymd,
            "source": "NSE fao_participant_oi CSV",
            "source_url": BASE_URLS[0].format(ddmmyyyy=_ddmmyyyy(date.fromisoformat(ymd))),
            "fetched_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S IST"),
            "participants": participants,
            # flat FII fields for dashboard columns
            "fii_idx_fut_long": fii.get("idx_fut_long"),
            "fii_idx_fut_short": fii.get("idx_fut_short"),
            "fii_idx_fut_long_pct": fii.get("idx_fut_long_pct"),
            "fii_idx_fut_short_pct": fii.get("idx_fut_short_pct"),
            "fii_idx_fut_long_display": fii.get("idx_fut_long_display"),
            "fii_idx_fut_short_display": fii.get("idx_fut_short_display"),
            "fii_idx_fut_net": fii.get("idx_fut_net"),
            "fii_idx_fut_ratio": fii.get("idx_fut_ratio"),
            "fii_idx_opt_pcr_short": fii.get("idx_opt_pcr_short"),
            "fii_total_long_display": fii.get("total_long_display"),
            "fii_total_short_display": fii.get("total_short_display"),
            # DII index fut (often mostly long hedges)
            "dii_idx_fut_long": dii.get("idx_fut_long"),
            "dii_idx_fut_short": dii.get("idx_fut_short"),
            "dii_idx_fut_long_display": dii.get("idx_fut_long_display"),
            "dii_idx_fut_short_display": dii.get("idx_fut_short_display"),
            "dii_idx_fut_ratio": dii.get("idx_fut_ratio"),
            # Client / Pro for context
            "client_idx_fut_long_display": client.get("idx_fut_long_display"),
            "client_idx_fut_short_display": client.get("idx_fut_short_display"),
            "pro_idx_fut_long_display": pro.get("idx_fut_long_display"),
            "pro_idx_fut_short_display": pro.get("idx_fut_short_display"),
        }
    return None
