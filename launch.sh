#!/bin/sh
# Used by the Desktop app: start server if not running, open browser
cd "$(dirname "$0")"
pgrep -x ollama >/dev/null || (ollama serve >/tmp/ollama.log 2>&1 &)
curl -s localhost:8000/api/docs >/dev/null || (nohup .venv/bin/uvicorn app:app --port 8000 >/tmp/rag.log 2>&1 &)
for i in 1 2 3 4 5 6 7 8 9 10; do curl -s localhost:8000/api/docs >/dev/null && break; sleep 1; done
open http://127.0.0.1:8000
