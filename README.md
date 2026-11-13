# Docs Chat

A private chatbot for your own documents. Upload **PDFs, PowerPoints, images and text files**, then ask questions. It finds the relevant parts, answers from them, and shows which file and page it used. It can also look at images and optionally "think" step by step.

Everything runs **on your own computer** with [Ollama](https://ollama.com). Nothing is uploaded anywhere, and there is no account or API key.

## Setup

1. Install [Ollama](https://ollama.com) and Python 3.10+.
2. Download models (these are the defaults; see "Use your own models" to change them):
   ```
   ollama pull qwen3:8b          # answers questions, can reason
   ollama pull qwen2.5vl:7b      # reads images and scanned pages
   ollama pull nomic-embed-text  # makes documents searchable
   ```
3. Install and run:
   ```
   git clone https://github.com/kanjin4998-cpu/docs-chat.git
   cd docs-chat
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ./run.sh
   ```
4. Open http://127.0.0.1:8000 and drag in some files.

## Use your own models

Set any model you have in Ollama with environment variables:

```
TEXT_MODEL=llama3.1:8b VISION_MODEL=gemma3:4b EMBED_MODEL=mxbai-embed-large ./run.sh
```

| Variable | What it does | Default |
|---|---|---|
| `TEXT_MODEL` | Answers text questions. A reasoning model (e.g. qwen3, deepseek-r1) enables the "Think" box. | `qwen3:8b` |
| `VISION_MODEL` | Looks at images and scanned pages. Must support images. | `qwen2.5vl:7b` |
| `EMBED_MODEL` | Makes documents searchable. If you change it, re-upload your files. | `nomic-embed-text` |
| `OLLAMA_URL` | Where Ollama runs. | `http://127.0.0.1:11434` |

## Privacy

Your uploaded files and their searchable index are stored only in the `data/` folder on your machine, which is excluded from git. Nothing is sent to the author or any third party.

## Limits

- Images inside PowerPoint slides are not read yet (slide text, tables and notes are).
- Questions that involve an image use the vision model, which does not do step-by-step thinking.
- Small local models make mistakes. Check important answers against the cited source.

MIT licensed.
