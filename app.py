"""Local RAG chatbot: upload PDF / PPTX / images, ask questions. Uses Ollama (free, local)."""
import base64, io, json, os, uuid
from pathlib import Path

import fitz  # pymupdf
import httpx
import numpy as np
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pptx import Presentation
from pydantic import BaseModel

# Pick your own models by setting these environment variables (any model installed in Ollama).
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
TEXT_MODEL = os.environ.get("TEXT_MODEL", "qwen3:8b")          # answers text questions (reasoning model recommended)
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")  # looks at images / scanned pages
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")  # turns text into searchable vectors
TOP_K = 5

ROOT = Path(__file__).parent
DATA = ROOT / "data"
IMAGES = DATA / "images"
IMAGES.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA / "db.json"

app = FastAPI()
# db = {"docs": {doc_id: {"name", "kind"}}, "chunks": [{"doc","text","where","image","vec"}]}
db = json.loads(DB_FILE.read_text()) if DB_FILE.exists() else {"docs": {}, "chunks": []}


def save():
    DB_FILE.write_text(json.dumps(db))


async def embed(texts):
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{OLLAMA}/api/embed", json={"model": EMBED_MODEL, "input": texts})
        r.raise_for_status()
        return r.json()["embeddings"]


async def describe(img_bytes, prompt):
    """Ask the vision model about one image."""
    b64 = base64.b64encode(img_bytes).decode()
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{OLLAMA}/api/chat", json={
            "model": VISION_MODEL, "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}]})
        r.raise_for_status()
        return r.json()["message"]["content"]


def split(text, size=900, overlap=150):
    text = " ".join(text.split())
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return [t for t in out if len(t.strip()) > 20]


OCR_PROMPT = "Transcribe all text in this image, then briefly describe any charts, diagrams or pictures."


async def extract(name, data):
    """Return (kind, [(where, text, image_filename_or_None)])."""
    ext = Path(name).suffix.lower()
    pieces = []
    if ext == ".pdf":
        pdf = fitz.open(stream=data, filetype="pdf")
        for n, page in enumerate(pdf, 1):
            text = page.get_text().strip()
            img = None
            if len(text) < 40:  # scanned page -> read it with the vision model
                png = page.get_pixmap(dpi=110).tobytes("png")
                text = await describe(png, OCR_PROMPT)
                img = f"{uuid.uuid4().hex}.png"
                (IMAGES / img).write_bytes(png)
            pieces.append((f"page {n}", text, img))
        return "pdf", pieces
    if ext in (".pptx",):
        prs = Presentation(io.BytesIO(data))
        for n, slide in enumerate(prs.slides, 1):
            parts = []
            for sh in slide.shapes:
                if sh.has_text_frame:
                    parts.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        parts.append(" | ".join(c.text for c in row.cells))
            if slide.has_notes_slide:
                parts.append("Notes: " + slide.notes_slide.notes_text_frame.text)
            pieces.append((f"slide {n}", "\n".join(parts), None))
        return "pptx", pieces
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        img = f"{uuid.uuid4().hex}{ext}"
        (IMAGES / img).write_bytes(data)
        text = await describe(data, OCR_PROMPT)
        return "image", [("image", text, img)]
    if ext in (".txt", ".md"):
        return "text", [("text", data.decode("utf-8", "ignore"), None)]
    raise ValueError(f"Unsupported file type: {ext}")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        try:
            kind, pieces = await extract(f.filename, await f.read())
            chunks = []
            for where, text, img in pieces:
                for t in split(text):
                    chunks.append({"text": t, "where": where, "image": img})
            if not chunks:
                raise ValueError("No readable text found")
            vecs = await embed([c["text"] for c in chunks])
            doc_id = uuid.uuid4().hex[:8]
            for c, v in zip(chunks, vecs):
                c.update(doc=doc_id, vec=v)
            db["docs"][doc_id] = {"name": f.filename, "kind": kind}
            db["chunks"].extend(chunks)
            results.append({"name": f.filename, "ok": True, "chunks": len(chunks)})
        except Exception as e:
            results.append({"name": f.filename, "ok": False, "error": str(e)})
    save()
    return results


@app.get("/api/docs")
def docs():
    return [{"id": k, **v} for k, v in db["docs"].items()]


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    db["docs"].pop(doc_id, None)
    db["chunks"] = [c for c in db["chunks"] if c["doc"] != doc_id]
    save()
    return {"ok": True}


@app.get("/api/image/{name}")
def image(name: str):
    p = IMAGES / Path(name).name
    return FileResponse(p)


async def retrieve(question):
    if not db["chunks"]:
        return []
    q = np.array((await embed([question]))[0])
    M = np.array([c["vec"] for c in db["chunks"]])
    sims = M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-9)
    return [db["chunks"][i] for i in np.argsort(-sims)[:TOP_K]]


class ChatReq(BaseModel):
    question: str
    history: list[dict] = []
    think: bool = True
    image: str | None = None  # base64 image attached to this message


SYSTEM = ("You answer using the provided document excerpts. Cite sources like [file, page 3]. "
          "If the excerpts don't contain the answer, say so instead of guessing.")


@app.post("/api/chat")
async def chat(req: ChatReq):
    hits = await retrieve(req.question)
    context = "\n\n".join(f"[{db['docs'][h['doc']]['name']}, {h['where']}]\n{h['text']}" for h in hits)
    images = [req.image] if req.image else []
    for h in hits[:2]:  # include the actual picture when an image/scanned page matched
        if h["image"] and len(images) < 3 and (IMAGES / h["image"]).exists():
            images.append(base64.b64encode((IMAGES / h["image"]).read_bytes()).decode())
    use_vision = bool(images)
    model = VISION_MODEL if use_vision else TEXT_MODEL

    user = req.question
    if context:
        user = f"Document excerpts:\n{context}\n\nQuestion: {req.question}"
    msgs = [{"role": "system", "content": SYSTEM}] + req.history[-8:]
    msgs.append({"role": "user", "content": user, **({"images": images} if use_vision else {})})
    body = {"model": model, "messages": msgs, "stream": True}
    if not use_vision and req.think:
        body["think"] = True
    elif not use_vision:
        body["think"] = False

    sources = [{"doc": db["docs"][h["doc"]]["name"], "where": h["where"], "image": h["image"]} for h in hits]

    async def gen():
        yield json.dumps({"sources": sources, "model": model}) + "\n"
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    m = json.loads(line).get("message", {})
                    if m.get("thinking"):
                        yield json.dumps({"thinking": m["thinking"]}) + "\n"
                    if m.get("content"):
                        yield json.dumps({"content": m["content"]}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")
