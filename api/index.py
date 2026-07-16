"""
Vercel serverless entrypoint.

All routes are rewritten to this ASGI app (see vercel.json).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Project root on PYTHONPATH (Vercel + local)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

# Vercel Python looks for `app` (ASGI)
__all__ = ["app"]
