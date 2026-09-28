"""Actual local Chroma tests; no embedding downloads, LLM or network service."""
import copy
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path):
    module = load("vector_test_server", SERVICE_DIR / "rag_server.py")
    module.DATA_DIR = tmp_path / "rag"
    return module


def test_embeddings_are_deterministic_normalized_256_dimensional(server):
    retrieval = server.rag_retrieval
    left, same, different = retrieval.embed_texts(["Python API evidence", "Python API evidence", "Flask Docker"])
    assert left == same and left != different
    assert len(left) == 256
    assert math.isclose(sum(value * value for value in left), 1)
    assert retrieval.embed_texts(["the and is"])[0] == [0.0] * 256
    many = retrieval.embed_texts([" ".join(f"term{number}" for number in range(1000))])[0]
    assert sum(value != 0 for value in many) > 128


def test_chunking_preserves_exact_excerpts_and_eighty_word_bound(server):
    text = " ".join(f"Sentence {i} has several words." for i in range(50))
    chunks = server.rag_retrieval.chunk_text(text)
    assert len(chunks) > 1
    assert all(chunk in text and len(chunk.split()) <= 80 for chunk in chunks)
    assert " ".join(chunks) == text


def test_refresh_uses_actual_persistent_chroma_with_source_metadata(server):
    index = server.get_index()
    refreshed = index.refresh("resume")
    assert refreshed["status"] == "success" and refreshed["vector_store_status"] == "ready"
    assert refreshed["document_count"] == 4 and refreshed["chunk_count"] == 5
    collection = index.client.get_collection(refreshed["collection"], embedding_function=None)
    stored = collection.get(include=["documents", "metadatas", "embeddings"])
    assert len(stored["embeddings"][0]) == 256
    assert all(len(text.split()) <= 80 for text in stored["documents"])
    assert all(meta["source"].startswith(meta["source_id"] + "#chunk-") for meta in stored["metadatas"])
    assert all(meta["indexed_at"] and meta["authority_tier"] == "tier_3" for meta in stored["metadatas"])
    reloaded = server.rag_retrieval.CorpusIndex(server.DATA_DIR, server.load_documents)
    answer = reloaded.retrieve("How can I write verifiable resume achievements?", 3, "resume")
    assert answer["retrieval_mode"] == "vector"
    assert answer["results"][0]["id"] == "achievement-writing"
    assert answer["corpus_version"] == refreshed["corpus_version"]
    assert answer["confidence"] == "medium"
    assert all(item["score"] > 0 and item["distance"] is not None for item in answer["results"])


@pytest.mark.parametrize("query", ["What is the weather in Sydney?", "Where is the nearest coffee shop?", "What is the capital of Japan?", "How many moons does Mars have?", "the and is"])
def test_vector_retrieval_rejects_unrelated_questions(server, query):
    result = server.retrieve(query, 5, "resume")
    assert result["retrieval_mode"] == "vector" and result["results"] == []
    assert result["confidence"] == "low"


def test_source_changes_require_controlled_refresh_and_old_index_is_preserved(server):
    index = server.get_index()
    first = index.refresh("resume")
    documents = copy.deepcopy(server.load_documents("resume"))
    documents[0]["text"] = "Kubernetes deployment outcomes require recorded project evidence."
    index.document_loader = lambda feature: documents
    assert index.status()["resume"]["stale"] is True
    with pytest.raises(server.rag_retrieval.CorpusError, match="Run POST /refresh"):
        index.retrieve("Kubernetes", 3, "resume")
    second = index.refresh("resume")
    assert first["corpus_version"] != second["corpus_version"]
    assert first["collection"] == second["previous_collection"]
    assert index.client.get_collection(first["collection"], embedding_function=None).count() == 5
    assert index.retrieve("Kubernetes deployment", 3, "resume")["results"][0]["text"] == documents[0]["text"]


def test_failed_staged_refresh_never_replaces_active_index(server):
    index = server.get_index()
    first = index.refresh("resume")
    original = index.client

    def fail(*args, **kwargs):
        raise RuntimeError("fixture index creation failure")

    index._client = SimpleNamespace(create_collection=fail, delete_collection=fail)
    with pytest.raises(server.rag_retrieval.CorpusError, match="previous active index retained"):
        index.refresh("resume")
    assert index._state()["resume"]["collection"] == first["collection"]
    index._client = original
    assert index.retrieve("resume evidence", 3, "resume")["retrieval_mode"] == "vector"


def test_vector_failure_is_an_explicit_degraded_fallback(server):
    index = server.get_index()
    index.refresh("resume")

    def fail(*args, **kwargs):
        raise RuntimeError("fixture unavailable index")

    index._client = SimpleNamespace(get_collection=fail)
    result = index.retrieve("resume evidence", 3, "resume")
    assert result["retrieval_mode"] == "lexical_fallback"
    assert result["vector_store_status"] == "degraded"
    assert result["warning"] and "fixture unavailable index" in result["vector_store_error"]
    assert result["results"] and all(item["distance"] is None for item in result["results"])
    assert result["confidence"] != "high"


def test_corrupted_validated_corpus_cannot_generate_context(server):
    index = server.get_index()
    refreshed = index.refresh("resume")
    (server.DATA_DIR / refreshed["corpus_file"]).write_text("tampered context")
    with pytest.raises(server.rag_retrieval.CorpusError, match="checksum"):
        index.retrieve("resume evidence", 3, "resume")


@pytest.mark.parametrize("payload", [{"feature": []}, {"feature": "outside"}, {"path": "/etc/passwd"}, None])
def test_refresh_has_no_arbitrary_source_or_path_control(server, payload):
    assert server.app.test_client().post("/refresh", json=payload).status_code == 400


@pytest.mark.parametrize("query,top_k,feature", [("", 3, "resume"), ("x" * 20001, 3, "resume"), ("resume", True, "resume"), ("resume", 0, "resume"), ("resume", 6, "resume"), ("resume", 3, [])])
def test_invalid_retrieval_bounds_are_rejected_before_index_use(server, query, top_k, feature):
    with pytest.raises(ValueError):
        server.retrieve(query, top_k, feature)
    assert not server.DATA_DIR.exists()


def test_http_refresh_and_corpus_status_expose_version_and_audit(server):
    client = server.app.test_client()
    response = client.post("/refresh", json={"feature": "resume"})
    assert response.status_code == 200
    state = client.get("/corpus").get_json()["corpora"]["resume"]
    assert state["stale"] is False and state["embedding_dimensions"] == 256
    client.post("/retrieve", json={"query": "resume evidence", "feature": "resume"})
    records = [json.loads(line) for line in (server.DATA_DIR / "rag-audit.jsonl").read_text().splitlines()]
    assert [record["operation"] for record in records] == ["refresh_corpus", "retrieve_context"]
    assert records[1]["corpus_version"] == state["corpus_version"]
    assert records[1]["retrieval_mode"] == "vector"


def test_real_chroma_benchmark_records_metrics_and_expected_sources(server):
    evaluation = load("vector_eval_test", SERVICE_DIR / "rag_eval.py")
    cases = json.loads((SERVICE_DIR / "retrieval_benchmarks.json").read_text())
    result = evaluation.evaluate(server.get_index(), cases)
    assert result["status"] == "pass"
    assert result["summary"]["all_queries_used_vector"] is True
    assert result["summary"]["mean_recall_at_5"] == 1
    assert result["summary"]["negative_queries_without_context"] == 3
    assert result["cases"][0]["vector"]["precision_at_5"] == 0.2


def test_benchmark_fails_when_fallback_would_otherwise_find_expected_sources(server):
    evaluation = load("degraded_eval_test", SERVICE_DIR / "rag_eval.py")
    index = server.get_index()
    original_retrieve = index.retrieve

    def degraded(*args, **kwargs):
        result = original_retrieve(*args, **kwargs)
        result.update(retrieval_mode="lexical_fallback", vector_store_status="degraded")
        return result

    index.retrieve = degraded
    cases = json.loads((SERVICE_DIR / "retrieval_benchmarks.json").read_text())
    result = evaluation.evaluate(index, cases)
    assert result["status"] == "fail"
    assert result["summary"]["all_queries_used_vector"] is False
    assert result["summary"]["mean_recall_at_5"] == 1


def test_changed_source_returns_http_dependency_error_until_refresh(server, monkeypatch):
    client = server.app.test_client()
    assert client.post("/refresh", json={"feature": "resume"}).status_code == 200
    changed = copy.deepcopy(server.load_documents("resume"))
    changed[0]["text"] += " Source change awaiting validation."
    monkeypatch.setattr(server, "load_documents", lambda feature: changed)
    blocked = client.post("/retrieve", json={"query": "resume evidence", "feature": "resume"})
    assert blocked.status_code == 503
    assert blocked.get_json()["dependency"] == "rag-corpus"
    assert "Run POST /refresh" in blocked.get_json()["error"]
    assert client.post("/refresh", json={"feature": "resume"}).status_code == 200
    assert client.post("/retrieve", json={"query": "resume evidence", "feature": "resume"}).status_code == 200
