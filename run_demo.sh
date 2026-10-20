#!/usr/bin/env bash
# macOS / Linux: one-time setup (if needed) and start the dashboard at http://localhost:8600
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  . .venv/bin/activate
fi
( sleep 3; (command -v xdg-open >/dev/null && xdg-open http://localhost:8600) || (command -v open >/dev/null && open http://localhost:8600) || true ) &
python -m uvicorn sectwin.api.server:app --host 127.0.0.1 --port 8600
