"""
Desktop entry point for the packaged DocsGPT.exe.

Seeds the demo corpus (idempotent), opens the browser, and runs the local
server. Data lives in ~/.docsgpt/ so it survives app restarts.
"""

import sys
import threading
import webbrowser

import engine
import server


def _open_browser_soon() -> None:
    """Give the server a moment to bind, then open the UI."""
    threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{server.PORT}",)).start()


def main() -> None:
    """Seed, open browser, serve."""
    print("[DOCS GPT] Desktop build — data folder:", engine.DATA_DIR)
    try:
        added = engine.seed_demo_corpus()
        if added:
            print(f"[DOCS GPT] Demo corpus loaded ({added} documents).")
    except engine.EngineError as exc:
        print(f"WARNING: demo corpus not loaded — {exc}")
    _open_browser_soon()
    try:
        server.main()
    except KeyboardInterrupt:
        print("[DOCS GPT] Stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
