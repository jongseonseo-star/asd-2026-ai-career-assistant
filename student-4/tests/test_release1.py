import asyncio
import importlib.util
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "student-4/backend"))
sys.path.insert(0, str(ROOT / "ai-services"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backend = load("jobs_backend_test", "student-4/backend/app.py")
frontend = load("jobs_frontend_test", "student-4/frontend/app.py")
mcp = load("jobs_mcp_test", "ai-services/mcp_server.py")
rag = load("jobs_rag_test", "ai-services/rag_server.py")
loop = load("jobs_loop_test", "ai-services/agentic_loop.py")


@pytest.fixture
def context():
    return {
        "job": {"id": 1, "company_id": 2, "title": "Developer", "description": "Build Python APIs"},
        "company": {"id": 2, "name": "Example"},
        "skills": [{"id": 3, "job_posting_id": 1, "skill_name": "Python", "importance": "required"}],
        "sources": ["db://student-4/job_postings/1", "db://student-4/companies/2", "db://student-4/job_skills/3"],
    }


@pytest.fixture
def retrieval():
    return {"feature": "jobs", "confidence": "medium", "confidence_basis": "Project-authored guidance.",
            "results": [{"title": "Skills", "text": "Prepare evidence of required skills.", "feature": "jobs",
                         "source": "repo://ai-services/knowledge/jobs/required-skills.md#chunk-1"}]}


def cited_generation(*_args):
    return {"claims": [{"text": "Prepare a Python project to demonstrate the listed skill.", "citations": ["J1", "G1"]}]}, {"called": True}


def call_tool(arguments):
    async def run():
        async with Client(mcp.mcp) as client:
            return await client.call_tool("job_context", arguments, raise_on_error=False)
    return asyncio.run(run())


def test_mcp_reads_only_selected_job_and_company(monkeypatch, context):
    records = {"/api/v1/job_postings/1": context["job"], "/api/v1/companies/2": context["company"],
               "/api/v1/job_skills": context["skills"] + [{"id": 4, "job_posting_id": 8}]}
    get = Mock(side_effect=lambda path: (records[path], 200))
    monkeypatch.setattr(mcp, "job_database_get", get)
    result = call_tool({"job_id": 1})
    assert not result.is_error
    assert result.structured_content == context
    assert get.call_count == 3


@pytest.mark.parametrize("arguments", [{"job_id": 0}, {"job_id": True}, {"job_id": "1"}, {"job_id": 1, "path": "/tmp"}])
def test_mcp_rejects_invalid_arguments_before_reading(monkeypatch, arguments):
    get = Mock()
    monkeypatch.setattr(mcp, "job_database_get", get)
    assert call_tool(arguments).is_error
    get.assert_not_called()


def test_mcp_propagates_missing_record(monkeypatch):
    monkeypatch.setattr(mcp, "job_database_get", lambda path: ({"error": "Not found"}, 404))
    result = call_tool({"job_id": 99})
    assert result.is_error
    assert result.structured_content["status_code"] == 404


def test_rag_routes_generate_cited_job_answer(monkeypatch, context, retrieval):
    monkeypatch.setattr(rag, "retrieve", lambda *args: retrieval)
    monkeypatch.setattr(rag.job_generation, "generate", cited_generation)
    response = rag.app.test_client().post("/answer", json={"task": "job-guidance", "feature": "jobs",
        "query": "required skills", "job_context": context})
    assert response.status_code == 200
    result = response.get_json()
    backend.validate_answer(result, context)
    assert result["claims"][0]["citations"] == ["J1", "G1"]


def test_no_context_never_calls_model(monkeypatch, context):
    generate = Mock(side_effect=AssertionError("Model must not be called"))
    monkeypatch.setattr(rag.job_generation, "generate", generate)
    retrieval = {"feature": "jobs", "results": [], "confidence": "low", "confidence_basis": "No matching context."}
    result = rag.job_generation.answer({"query": "weather", "job_context": context}, retrieval)
    assert result["status"] == "insufficient-context"
    assert result["claims"] == []
    generate.assert_not_called()


@pytest.mark.parametrize("field,value", [("company", {"id": 9, "name": "Wrong company"}), ("sources", [])])
def test_rag_rejects_inconsistent_context(monkeypatch, context, field, value):
    context[field] = value
    retrieve = Mock()
    monkeypatch.setattr(rag, "retrieve", retrieve)
    response = rag.app.test_client().post("/answer", json={"task": "job-guidance", "feature": "jobs",
        "query": "skills", "job_context": context})
    assert response.status_code == 400
    retrieve.assert_not_called()


def test_job_corpus_has_retrieval_and_no_match_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "_index", rag.rag_retrieval.CorpusIndex(tmp_path, rag.load_documents))
    rag.get_index().refresh("jobs")
    result = rag.retrieve("required job skills preparation evidence", feature="jobs")
    assert result["results"] and result["retrieval_mode"] == "vector"
    assert all(item["feature"] == "jobs" for item in result["results"])
    assert not rag.retrieve("What is the weather in Sydney?", feature="jobs")["results"]


def test_backend_disabled_without_contacting_mcp(monkeypatch):
    monkeypatch.setattr(backend, "AI_SERVICES_ENABLED", False)
    read = AsyncMock()
    monkeypatch.setattr(backend, "read_mcp_job", read)
    assert backend.app.test_client().post("/api/v1/mcp/jobs/1/context").status_code == 503
    read.assert_not_called()


def test_backend_preserves_mcp_domain_errors(monkeypatch):
    monkeypatch.setattr(backend, "AI_SERVICES_ENABLED", True)
    monkeypatch.setattr(backend, "read_mcp_job", AsyncMock(side_effect=backend.ServiceError("Not found", 404, "mcp")))
    assert backend.app.test_client().post("/api/v1/mcp/jobs/99/context").status_code == 404


@pytest.mark.parametrize("body", [{}, {"query": " "}, {"query": "x" * 2001}, {"query": "skills", "job_context": {}}])
def test_backend_rejects_bad_questions(monkeypatch, body):
    read = Mock()
    monkeypatch.setattr(backend, "mcp_job", read)
    assert backend.app.test_client().post("/api/v1/rag/jobs/1/answer", json=body).status_code == 400
    read.assert_not_called()


def test_backend_rejects_unknown_citations(monkeypatch, context, retrieval):
    monkeypatch.setattr(rag.job_generation, "generate", cited_generation)
    result = rag.job_generation.answer({"query": "skills", "job_context": context}, retrieval)
    result["claims"][0]["citations"] = ["invented"]
    monkeypatch.setattr(backend, "mcp_job", lambda job_id: context)
    monkeypatch.setattr(backend.session, "post", lambda *args, **kwargs: Mock(ok=True, json=lambda: result))
    response = backend.app.test_client().post("/api/v1/rag/jobs/1/answer", json={"query": "skills"})
    assert response.status_code == 502


def test_frontend_renders_citations_and_escapes_text(monkeypatch, context, retrieval):
    monkeypatch.setattr(rag.job_generation, "generate", cited_generation)
    result = rag.job_generation.answer({"query": "skills", "job_context": context}, retrieval)
    result["claims"][0]["text"] = "<script>alert(1)</script>"
    monkeypatch.setattr(frontend, "api", lambda *args, **kwargs: Mock(ok=True, json=lambda: result))
    response = frontend.app.test_client().post("/rag/jobs/1/answer", data={"query": "skills"})
    text = response.get_data(as_text=True)
    assert "Confidence: Medium" in text and "J1, G1" in text
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert retrieval["results"][0]["source"] in text


def test_loop_checks_selected_job_and_preserves_evidence(context):
    assert not loop.validate_mcp_payload(context, "jobs", 1, 1, "unused", job_id=1)
    assert loop.validate_mcp_payload(context, "jobs", 1, 1, "unused", job_id=2)
    observed = loop.assessment_evidence("mcp", "jobs", [{"name": "job", "passed": True, "payload": context}])
    assert observed["checks"][0]["job_context"] == context


def test_legacy_ai_has_bounded_output(monkeypatch):
    monkeypatch.setattr(backend, "OLLAMA_ENABLED", True)
    response = Mock()
    response.json.return_value = {"message": {"content": "A concise summary."}}
    post = Mock(return_value=response)
    monkeypatch.setattr(backend.session, "post", post)
    assert backend.ollama_generate("Summarise this job", {}) == "A concise summary."
    assert post.call_args.kwargs["json"]["options"]["num_predict"] == 800
