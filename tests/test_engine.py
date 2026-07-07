"""Unit tests for the no-API parts of the Docs GPT engine."""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402  pylint: disable=wrong-import-position


def test_extract_text_plain() -> None:
    """Plain text and markdown pass through decoded."""
    assert engine.extract_text("note.txt", b"hello world") == "hello world"
    assert engine.extract_text("note.md", "séal water".encode("utf-8")) == "séal water"


def test_extract_text_rejects_unknown_extension() -> None:
    """Unknown file types raise a loud EngineError."""
    with pytest.raises(engine.EngineError):
        engine.extract_text("data.xlsx", b"whatever")


def test_extract_text_rejects_empty() -> None:
    """Empty files raise instead of silently storing nothing."""
    with pytest.raises(engine.EngineError):
        engine.extract_text("empty.txt", b"   ")


def test_score_document_counts_terms() -> None:
    """Keyword scoring counts question-term occurrences, case-insensitive."""
    text = "Seal water pressure must be 350 kPa. Seal water flushes the gland."
    assert engine.score_document("What is the seal water pressure?", text) >= 4
    assert engine.score_document("crane inspection", text) == 0


def test_select_corpus_within_budget_keeps_all() -> None:
    """When everything fits the budget, nothing is dropped."""
    docs = [
        {"id": "a", "chars": 100, "text": "pump seal water"},
        {"id": "b", "chars": 100, "text": "confined space"},
    ]
    selected, dropped = engine.select_corpus("seal water", docs)
    assert len(selected) == 2
    assert not dropped


def test_select_corpus_over_budget_drops_least_relevant() -> None:
    """Over budget, the least relevant document is dropped — never silently."""
    big = engine.CORPUS_CHAR_BUDGET // 2 + 1
    docs = [
        {"id": "relevant", "chars": big, "text": "seal water " * 50},
        {"id": "irrelevant", "chars": big, "text": "unrelated crane content"},
    ]
    selected, dropped = engine.select_corpus("seal water pressure", docs)
    assert [doc["id"] for doc in selected] == ["relevant"]
    assert [doc["id"] for doc in dropped] == ["irrelevant"]


def test_number_citations_dedupes_and_orders() -> None:
    """Identical spans share one number; distinct spans count up in order."""
    span_a = {"doc_id": "d1", "start": 0, "end": 10}
    span_b = {"doc_id": "d1", "start": 20, "end": 30}
    segments = [
        {"text": "first", "citations": [dict(span_a)]},
        {"text": "second", "citations": [dict(span_b), dict(span_a)]},
    ]
    evidence = engine.number_citations(segments)
    assert [cite["n"] for cite in evidence] == [1, 2]
    assert segments[0]["citations"][0]["n"] == 1
    assert segments[1]["citations"][0]["n"] == 2
    assert segments[1]["citations"][1]["n"] == 1
    assert len(evidence) == 2


def test_refusal_sentence_is_stable() -> None:
    """The refusal sentinel the UI relies on must not drift."""
    assert engine.REFUSAL_SENTENCE == "Not found in your documents."
    assert engine.REFUSAL_SENTENCE in engine.SYSTEM_PROMPT


# ---------------- Phase 1: workspaces + BYO keys ----------------


def test_validate_workspace_accepts_uuid_and_default() -> None:
    """Browser UUIDs and the default workspace pass validation."""
    assert engine.validate_workspace("default") == "default"
    uuid_like = "3f2a1b4c-9d8e-4f00-a1b2-c3d4e5f60718"
    assert engine.validate_workspace(uuid_like) == uuid_like


def test_validate_workspace_rejects_traversal() -> None:
    """Path-traversal and junk ids are refused loudly."""
    for bad in ("../evil", "..", "C:/x", "UPPER", "", "a b", "x" * 100):
        with pytest.raises(engine.EngineError):
            engine.validate_workspace(bad)


def test_workspace_isolation(tmp_path, monkeypatch) -> None:
    """A doc added in workspace A is invisible in workspace B and default."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    ws_a = "aaaaaaaa-1111-4222-8333-444444444444"
    ws_b = "bbbbbbbb-1111-4222-8333-444444444444"
    engine.add_document("a.txt", b"seal water pressure", workspace=ws_a)
    assert len(engine.list_documents(ws_a)) == 1
    assert not engine.list_documents(ws_b)
    assert not engine.list_documents()


def test_workspace_doc_cap(tmp_path, monkeypatch) -> None:
    """Non-default workspaces refuse uploads beyond the cap."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    monkeypatch.setattr(engine, "MAX_DOCS_PER_WORKSPACE", 2)
    ws = "cccccccc-1111-4222-8333-444444444444"
    engine.add_document("one.txt", b"one", workspace=ws)
    engine.add_document("two.txt", b"two", workspace=ws)
    with pytest.raises(engine.EngineError):
        engine.add_document("three.txt", b"three", workspace=ws)


def test_default_workspace_has_no_cap(tmp_path, monkeypatch) -> None:
    """The local default workspace is never capped."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    monkeypatch.setattr(engine, "MAX_DOCS_PER_WORKSPACE", 1)
    engine.add_document("one.txt", b"one")
    engine.add_document("two.txt", b"two")
    assert len(engine.list_documents()) == 2


def test_purge_stale_workspaces(tmp_path, monkeypatch) -> None:
    """Idle workspaces are deleted; fresh ones and default are kept."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    stale = "dddddddd-1111-4222-8333-444444444444"
    fresh = "eeeeeeee-1111-4222-8333-444444444444"
    engine.add_document("old.txt", b"old", workspace=stale)
    engine.add_document("new.txt", b"new", workspace=fresh)
    engine.add_document("local.txt", b"local")
    two_days_ago = time.time() - 48 * 3600
    for item in (tmp_path / "ws" / stale).rglob("*"):
        os.utime(item, (two_days_ago, two_days_ago))
    os.utime(tmp_path / "ws" / stale, (two_days_ago, two_days_ago))
    purged = engine.purge_stale_workspaces(max_idle_hours=24)
    assert purged == [stale]
    assert not (tmp_path / "ws" / stale).exists()
    assert (tmp_path / "ws" / fresh).exists()
    assert engine.list_documents()


def test_resolve_api_key_order(tmp_path, monkeypatch) -> None:
    """Key resolution: request key beats env; env beats saved config; none raises."""
    monkeypatch.setattr(engine, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert engine.resolve_api_key("sk-request") == "sk-request"
    assert engine.resolve_api_key(None) == "sk-env"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    engine.save_api_key("sk-saved")
    assert engine.resolve_api_key(None) == "sk-saved"
    assert engine.saved_key_present()
    engine.save_api_key("")
    assert not engine.saved_key_present()
    with pytest.raises(engine.EngineError):
        engine.resolve_api_key(None)


def test_seed_demo_corpus_is_idempotent(tmp_path, monkeypatch) -> None:
    """Seeding a workspace twice adds the demo docs exactly once."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    ws = "ffffffff-1111-4222-8333-444444444444"
    assert engine.seed_demo_corpus(ws) == len(engine.DEMO_DOCS)
    assert engine.seed_demo_corpus(ws) == 0
    assert engine.workspace_exists(ws)
    assert len(engine.list_documents(ws)) == len(engine.DEMO_DOCS)
