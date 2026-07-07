"""
Seed the Docs GPT library with the synthetic demo corpus (idempotent).

Run once: python seed_demo.py
Skips any demo doc whose title is already in the library. The seeding logic
lives in engine.seed_demo_corpus so the online server can reuse it per
workspace.
"""

import sys

import engine


def main() -> None:
    """Load the demo documents into the default (local) workspace."""
    try:
        added = engine.seed_demo_corpus()
        skipped = len(engine.DEMO_DOCS) - added
        print(f"[DONE] {added} document(s) added, {skipped} skipped.")
    except engine.EngineError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
