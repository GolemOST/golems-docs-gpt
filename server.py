"""
Docs GPT — Flask server, local or online.

Serves the single-page UI from static/ and a small JSON API around engine.py.

Modes (DOCSGPT_MODE env, default "local"):
- local:  single-user; default workspace; binds 127.0.0.1 unless DOCSGPT_HOST
  is set (e.g. a Tailscale IP for phone access). Never bind 0.0.0.0 locally.
- online: multi-user; every request needs an X-Workspace header (browser-minted
  UUID); new workspaces are seeded with the demo corpus; stale workspaces are
  purged after 24 h; keys arrive per-request via X-Api-Key and are never stored.
"""

import base64
import binascii
import os
import sys
import threading
import time
from collections import defaultdict, deque

from flask import Flask, jsonify, request

import engine

MODE = os.getenv("DOCSGPT_MODE", "local").lower()
ONLINE = MODE == "online"
HOST = os.getenv("DOCSGPT_HOST", "0.0.0.0" if ONLINE else "127.0.0.1")
PORT = int(os.getenv("PORT", "8756"))

PURGE_IDLE_HOURS = 24.0
PURGE_EVERY_SECONDS = 3600
RATE_LIMITS = {"ask": (10, 60.0), "upload": (20, 60.0)}

app = Flask(__name__, static_folder=str(engine.APP_DIR / "static"), static_url_path="")

_rate_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_rate_lock = threading.Lock()


def _workspace() -> str:
    """Resolve the request's workspace: header online, default locally."""
    header = (request.headers.get("X-Workspace") or "").strip()
    if not header:
        if ONLINE:
            raise engine.EngineError("Missing workspace id — refresh the page.")
        return engine.DEFAULT_WORKSPACE
    return engine.validate_workspace(header)


def _throttled(action: str, workspace: str) -> bool:
    """Fixed-window rate limit per workspace; True when over the limit."""
    limit, window = RATE_LIMITS[action]
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits[(action, workspace)]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
    return False


def _purge_loop() -> None:
    """Hourly cleanup of stale online workspaces (daemon thread)."""
    while True:
        try:
            purged = engine.purge_stale_workspaces(PURGE_IDLE_HOURS)
            if purged:
                print(f"[DOCS GPT] Purged {len(purged)} stale workspace(s).")
        except (OSError, engine.EngineError) as exc:
            print(f"WARNING: workspace purge failed — {exc}")
        time.sleep(PURGE_EVERY_SECONDS)


@app.get("/")
def index():
    """Serve the single-page UI."""
    return app.send_static_file("index.html")


@app.get("/api/config")
def api_config():
    """Tell the UI which mode it runs in and whether a server-side key exists."""
    return jsonify({
        "mode": MODE,
        "model": engine.MODEL,
        "has_env_key": engine.env_key_present(),
        "has_saved_key": False if ONLINE else engine.saved_key_present(),
        "max_docs": engine.MAX_DOCS_PER_WORKSPACE if ONLINE else None,
        "purge_hours": PURGE_IDLE_HOURS if ONLINE else None,
    })


@app.post("/api/config/key")
def api_config_key():
    """Save (or clear, empty key) the BYO key locally. Local installs only."""
    if ONLINE:
        return jsonify({"error": "Keys are never stored on the online server — "
                                 "your key stays in your browser."}), 403
    payload = request.get_json(silent=True) or {}
    try:
        engine.save_api_key(payload.get("key", ""))
        return jsonify({"saved": engine.saved_key_present()})
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/library")
def api_library():
    """List a workspace's documents; online, first touch seeds the demo corpus."""
    try:
        workspace = _workspace()
        if ONLINE and not engine.workspace_exists(workspace):
            engine.seed_demo_corpus(workspace)
        return jsonify({"documents": engine.list_documents(workspace)})
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/upload")
def api_upload():
    """Register an uploaded file. Body: {filename, data_b64, title?, rev?, status?}."""
    payload = request.get_json(silent=True) or {}
    filename = (payload.get("filename") or "").strip()
    data_b64 = payload.get("data_b64") or ""
    if not filename or not data_b64:
        return jsonify({"error": "filename and data_b64 are required"}), 400
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "data_b64 is not valid base64"}), 400
    try:
        workspace = _workspace()
        if _throttled("upload", workspace):
            return jsonify({"error": "Too many uploads — wait a minute."}), 429
        meta = engine.add_document(
            filename,
            raw,
            title=payload.get("title", ""),
            rev=payload.get("rev", ""),
            status=payload.get("status", "current"),
            workspace=workspace,
        )
        return jsonify({"document": meta})
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/ask")
def api_ask():
    """Answer a question from the workspace. Body: {question, include_superseded?}."""
    payload = request.get_json(silent=True) or {}
    try:
        workspace = _workspace()
        if _throttled("ask", workspace):
            return jsonify({"error": "Too many questions — wait a minute."}), 429
        result = engine.ask(
            payload.get("question", ""),
            include_superseded=bool(payload.get("include_superseded", False)),
            workspace=workspace,
            api_key=request.headers.get("X-Api-Key"),
        )
        return jsonify(result)
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/doc/<doc_id>")
def api_doc(doc_id: str):
    """Return one document's metadata and full extracted text (for the viewer)."""
    try:
        return jsonify({"document": engine.get_document(doc_id, _workspace())})
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/api/doc/<doc_id>/status")
def api_doc_status(doc_id: str):
    """Toggle a document between current and superseded. Body: {status}."""
    payload = request.get_json(silent=True) or {}
    try:
        meta = engine.set_status(doc_id, payload.get("status", ""), _workspace())
        return jsonify({"document": meta})
    except engine.EngineError as exc:
        return jsonify({"error": str(exc)}), 400


if ONLINE:
    threading.Thread(target=_purge_loop, daemon=True).start()


def main() -> None:
    """Start the server with Flask's dev server (local use; Render uses gunicorn)."""
    print(f"[DOCS GPT] Mode: {MODE} | Model: {engine.MODEL}")
    print(f"[DOCS GPT] Serving on http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        app.run(host=HOST, port=PORT, debug=False)
    except OSError as exc:
        print(f"ERROR: Cannot bind {HOST}:{PORT} — {exc}")
        print("Is another Docs GPT instance already running?")
        sys.exit(1)


if __name__ == "__main__":
    main()
