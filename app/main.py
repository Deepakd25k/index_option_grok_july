"""FastAPI app — local HTML dashboard + refresh API."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import storage
from app.pipeline import run_refresh

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DOCS = ROOT / "docs"

app = FastAPI(title="Premarket Dashboard", version="1.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    from app.fetchers import upstox_enabled

    return {
        "ok": True,
        "upstox_token_set": upstox_enabled(),
        "has_latest": storage.load_latest() is not None,
    }


@app.get("/api/latest")
def latest():
    data = storage.load_latest()
    if not data:
        return JSONResponse({"ok": False, "error": "no data yet — call /api/refresh"}, status_code=404)
    return {"ok": True, "data": data}


@app.get("/api/history")
def history(limit: int = 60):
    return {"ok": True, **storage.history_for_ui(limit)}


@app.get("/api/schema")
def schema():
    from app.config import DAILY_COLUMNS

    return {"ok": True, "columns": DAILY_COLUMNS}


@app.get("/api/docs")
def docs():
    """Significance guide as simple HTML (no extra deps)."""
    path = DOCS / "SIGNIFICANCE.md"
    if not path.exists():
        return JSONResponse({"ok": False, "error": "docs missing"}, status_code=404)
    md = path.read_text(encoding="utf-8")
    return {"ok": True, "markdown": md, "html": _md_lite(md)}


@app.post("/api/refresh")
@app.get("/api/refresh")
def refresh():
    try:
        snap = run_refresh()
        return {"ok": True, "data": snap}
    except Exception as e:
        log.exception("refresh failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/upstox-status")
def upstox_status():
    """Diagnose why Structure/chain may fail while Live shows prices."""
    try:
        from app import upstox_api as ux
        from app.fetchers import fetch_yahoo_all

        token_on = ux.enabled()
        quotes_ok = False
        chain_n = 0
        contracts_n = 0
        expiries: list = []
        err = {}
        if token_on:
            q = ux.quotes([ux.IDX["nifty"]])
            quotes_ok = bool(q)
            contracts = ux.option_contracts(ux.IDX["nifty"])
            contracts_n = len(contracts)
            expiries = ux.list_expiries(ux.IDX["nifty"])[:5]
            chain = ux.option_chain(ux.IDX["nifty"])
            chain_n = len(chain)
            err = dict(ux.LAST_ERROR or {})
        y = {}
        try:
            y = fetch_yahoo_all()
        except Exception:
            pass
        return {
            "ok": True,
            "token_set": token_on,
            "upstox_quotes_ok": quotes_ok,
            "option_contracts": contracts_n,
            "expiries": expiries,
            "option_chain_strikes": chain_n,
            "last_error": err,
            "yahoo_nifty": y.get("nifty_display"),
            "hint": (
                "Structure needs token_set=true AND option_chain_strikes>0. "
                "If token_set=false but yahoo_nifty has value, Live is Yahoo not Upstox."
            ),
        }
    except Exception as e:
        log.exception("upstox-status")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/live-chain")
@app.post("/api/live-chain")
def live_chain():
    """ATM±3 Call|Strike|Put board with 5/15/30m/day OI & premium levels (Upstox).

    Heavier than /api/live — poll every ~12–15s. Prices still use /api/live @ 3s.
    """
    try:
        from app.oi_board import build_chain_board
        from app.calendar_util import now_str

        board = build_chain_board(band=3, with_windows=True)
        return {
            "ok": bool(board.get("ok")),
            "last_updated": now_str(),
            "oi_board": board,
            "error": board.get("error"),
        }
    except Exception as e:
        log.exception("live-chain")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/live")
@app.post("/api/live")
def live_indices():
    """Continuous live feed — **Upstox primary** (Nifty/BN/Sensex/VIX/GIFT + near futures).

    Poll this every few seconds from the UI. Yahoo is only used if Upstox token
    missing or a symbol fails — so live path stays fast and broker-true.
    """
    try:
        from app import upstox_api as ux
        from app.calendar_util import now_str
        from app.fetchers import fetch_yahoo_all, format_price_chg

        bundle = ux.live_index_bundle()
        indices = bundle.get("indices") or {}
        futures = bundle.get("futures") or {}
        source = "upstox" if bundle.get("ok") else "none"

        # Yahoo fallback only for missing symbols (no token / partial fail)
        y = {}
        need_fallback = not bundle.get("ok") or any(
            k not in indices for k in ("nifty", "banknifty", "sensex", "vix")
        )
        if need_fallback:
            try:
                y = fetch_yahoo_all()
                source = "upstox+yahoo" if bundle.get("ok") else "yahoo"
            except Exception:
                y = {}

        keys = ("nifty", "banknifty", "sensex", "vix", "gift")
        out: dict = {
            "ok": True,
            "last_updated": bundle.get("ts") or now_str(),
            "source": source,
            "upstox": ux.enabled(),
            "live": True,
        }
        for k in keys:
            rec = indices.get(k) or {}
            price = rec.get("price")
            chg = rec.get("chg_pct")
            disp = rec.get("display")
            if price is None and y.get(k) is not None:
                price = y.get(k)
                chg = y.get(f"{k}_chg_pct")
                disp = y.get(f"{k}_display") or format_price_chg(price, chg)
            out[k] = price
            out[f"{k}_chg_pct"] = chg
            out[f"{k}_display"] = disp or format_price_chg(price, chg)
            if rec.get("open") is not None:
                out[f"{k}_ohlc"] = {
                    "o": rec.get("open"),
                    "h": rec.get("high"),
                    "l": rec.get("low"),
                    "c": rec.get("close"),
                }
        # Futures LTPs (Upstox only)
        out["futures"] = {
            name: {
                "price": f.get("price"),
                "display": f.get("display"),
                "chg_pct": f.get("chg_pct"),
                "symbol": f.get("trading_symbol"),
                "expiry": f.get("expiry"),
            }
            for name, f in futures.items()
        }
        if not out.get("nifty") and not out.get("banknifty"):
            out["ok"] = False
            out["error"] = bundle.get("error") or "No live quotes"
        return out
    except Exception as e:
        log.exception("live")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


def _md_lite(md: str) -> str:
    """Minimal markdown → HTML for the Significance tab."""
    lines = md.splitlines()
    out: list[str] = []
    in_table = False
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            continue
        if line.startswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                out.append("<table>")
                out.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
            if line.startswith("|"):
                continue
        if re.match(r"^### ", line):
            out.append(f"<h3>{line[4:]}</h3>")
        elif re.match(r"^## ", line):
            out.append(f"<h2>{line[3:]}</h2>")
        elif re.match(r"^# ", line):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.strip().startswith("- "):
            out.append(f"<li>{line.strip()[2:]}</li>")
        elif line.strip() == "---":
            out.append("<hr/>")
        elif line.strip():
            # bold **x**
            t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
            out.append(f"<p>{t}</p>")
    if in_table:
        out.append("</table>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)
