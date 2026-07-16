#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "  Premarket Dashboard"
echo "  http://127.0.0.1:8765"
echo ""
echo "  UPSTOX_ACCESS_TOKEN set? → full auto incl. GIFT Nifty"
echo "  Without token → Yahoo + FII/DII still work (GIFT may be empty)"
echo ""

export PYTHONPATH=.
exec uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
