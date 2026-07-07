# Golem's Docs GPT — answers only from YOUR documents

Upload your SOPs, procedures, or technical documents. Ask a question. Get an
answer grounded **only** in those documents — with an evidence panel of verbatim
quotes, each deep-linked to the exact highlighted passage in the source.

Built on the Claude **Citations API**: every supported claim carries a real,
clickable citation. If your documents don't contain the answer, the app says
exactly *"Not found in your documents."* — it never fills the gap from general
knowledge.

**Bring your own Anthropic API key** (get one at console.anthropic.com). Your
question and your documents' text go to Anthropic on *your* key — you pay only
your own usage. The hosted demo never stores your key.

---

## Try it online

The hosted demo runs a temporary per-browser workspace, pre-loaded with a
synthetic demo corpus (4 fictional plant SOPs):

1. Open the app, click **⚙ Settings**, paste your Anthropic API key
   (it stays in your browser).
2. Try: *"What are the acceptable gas test limits for confined space entry?"*
3. Click any citation — the source document opens with the exact passage highlighted.
4. Upload your own .pdf / .docx / .txt / .md (15 MB each, 20 docs max).

⚠ The hosted demo is a **demo, not a document vault**: workspaces are deleted
after ~24 hours of inactivity (and on server restarts). Never upload
confidential or personal documents.

## Run it on your own PC (private)

Everything stays on your machine except the question + document text sent to
Anthropic when you ask.

```
git clone https://github.com/GolemOST/golems-docs-gpt
cd golems-docs-gpt
pip install -r requirements.txt
python seed_demo.py     # optional: load the demo corpus
python server.py        # open http://127.0.0.1:8756
```

Or just double-click **`Start Docs GPT.bat`** (Windows, Python 3.11+ installed).

First run: click **⚙ Settings**, paste your key, choose **Save on this PC**
(stored in `~/.docsgpt/config.json`) — or set the `ANTHROPIC_API_KEY`
environment variable.

## What makes it honest

- **Refusal path** — no answer in your docs → *"Not found in your documents."*
  plus an amber **unverified** banner. Zero-citation answers get flagged too.
- **Verbatim evidence** — citations are exact character spans returned by the
  Citations API, mapped 1:1 into the stored text. A quote can't be faked.
- **Version awareness** — mark documents *current* or *superseded*; superseded
  docs are excluded from answers unless you opt in, and their citations are ⚠-flagged.
- **Honest assembly** — every answer states which documents were searched,
  which were cited, and whether any were skipped for size. Never silent.
- **The document is the authority** — the answer is a pointer. Open the
  citation before acting.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `DOCSGPT_MODE` | `local` | `online` = multi-user demo mode (per-browser workspaces, 24 h purge, rate limits) |
| `DOCSGPT_HOST` | `127.0.0.1` | Bind address (local mode never exposes itself to your network by default) |
| `PORT` | `8756` | Listen port |
| `DOCSGPT_MODEL` | `claude-opus-4-8` | Claude model to use |
| `DOCSGPT_ENV_FILE` | — | Optional extra `.env` file to load |

## Limits (v1)

- Scanned (image-only) PDFs are not supported — no OCR yet.
- Corpus per question is capped at 350k characters; least-relevant documents
  are dropped beyond that (and the answer footer tells you).

## Tests

```
pip install pytest
python -m pytest tests/
```

MIT licensed. Built with Flask, pypdf, python-docx, and the Anthropic Python SDK.
