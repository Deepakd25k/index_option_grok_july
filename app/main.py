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
