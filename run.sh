#!/bin/sh
# Starts Ollama (if needed) and the chat app, then open http://127.0.0.1:8000
cd "$(dirname "$0")"
pgrep -x ollama >/dev/null || (ollama serve >/tmp/ollama.log 2>&1 &)
.venv/bin/uvicorn app:app --port 8000
