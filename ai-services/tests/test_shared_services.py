"""Shared service tests. MCP uses the real protocol and a fixture HTTP database, no LLM."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread

from fastmcp import Client
import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rag():
    return load_module("rag_test_module", SERVICE_DIR / "rag_server.py")


@pytest.fixture
def candidate_api():
    records = {
        "/api/v1/profiles/1": {"id": 1, "full_name": "Fixture Candidate", "target_role": "Engineer"},
        "/api/v1/resumes/1": {"id": 1, "candidate_profile_id": 1, "content": "Python API project"},
        "/api/v1/resumes/2": {"id": 2, "candidate_profile_id": 2, "content": "Other candidate"},
        "/api/v1/skills?candidate_profile_id=1": [{"id": 4, "candidate_profile_id": 1, "skill_name": "Python"}],
    }
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            data = records.get(self.path)
            self.send_response(200 if data is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data or {"error": "Not found"}).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", records, seen
    server.shutdown()
    server.server_close()
    thread.join()


def test_real_mcp_reads_current_records_and_preserves_interview_tool(candidate_api, monkeypatch):
    base, records, seen = candidate_api
    mcp_module = load_module("mcp_test_live_records", SERVICE_DIR / "mcp_server.py")
    monkeypatch.setattr(mcp_module, "DATABASE_API_URL", base)

    async def scenario():
        async with Client(mcp_module.mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert {"resume_context", "interview_context"} <= names
            response = await client.call_tool("resume_context", {"profile_id": 1, "resume_id": 1})
            assert response.is_error is False
            context = response.structured_content
            assert context["candidate_profile"]["full_name"] == "Fixture Candidate"
            assert context["candidate_skills"][0]["skill_name"] == "Python"
            assert "db://student-2/skills/4" in context["sources"]
            records["/api/v1/resumes/1"]["content"] = "Updated through DB fixture"
            updated = await client.call_tool("resume_context", {"profile_id": 1, "resume_id": 1})
            assert updated.structured_content["resume"]["content"] == "Updated through DB fixture"
            interview = await client.call_tool("interview_context", {"target_role": "Engineer"})
            assert interview.is_error is False
            assert interview.structured_content["target_role"] == "Engineer"

    asyncio.run(scenario())
    assert seen.count("/api/v1/resumes/1") == 2
    assert "/api/v1/skills?candidate_profile_id=1" in seen


@pytest.mark.parametrize("profile_id,resume_id,expected", [(1, 2, 400), (999, 1, 404), (0, 1, 400)])
def test_mcp_rejects_mismatched_or_missing_candidate(candidate_api, monkeypatch, profile_id, resume_id, expected):
    base, _, _ = candidate_api
    module = load_module("mcp_test_errors", SERVICE_DIR / "mcp_server.py")
    monkeypatch.setattr(module, "DATABASE_API_URL", base)

    async def scenario():
        async with Client(module.mcp) as client:
            result = await client.call_tool("resume_context", {"profile_id": profile_id, "resume_id": resume_id}, raise_on_error=False)
            assert result.is_error is True
            assert result.structured_content["status_code"] == expected
            assert result.structured_content["error"]
            assert "candidate_profile" not in result.structured_content
    asyncio.run(scenario())


def test_mcp_rejects_cross_candidate_skills(candidate_api, monkeypatch):
    base, records, _ = candidate_api
    records["/api/v1/skills?candidate_profile_id=1"][0]["candidate_profile_id"] = 2
    module = load_module("mcp_test_bad_skills", SERVICE_DIR / "mcp_server.py")
    monkeypatch.setattr(module, "DATABASE_API_URL", base)
    async def scenario():
        async with Client(module.mcp) as client:
            result = await client.call_tool("resume_context", {"profile_id": 1, "resume_id": 1}, raise_on_error=False)
            assert result.is_error is True
            assert result.structured_content["status_code"] == 502
    asyncio.run(scenario())


@pytest.mark.parametrize("arguments", [
    {"profile_id": 0, "resume_id": 1}, {"profile_id": -1, "resume_id": 1},
    {"profile_id": True, "resume_id": 1}, {"profile_id": "1", "resume_id": 1},
    {"profile_id": 1}, {"profile_id": 1, "resume_id": 1, "extra": "unexpected"},
])
def test_mcp_invalid_input_is_structured_tool_error_without_database(monkeypatch, arguments):
    module = load_module("mcp_test_invalid_input", SERVICE_DIR / "mcp_server.py")

    def forbidden_database(*_args):
        raise AssertionError("Invalid tool input must not access the database")

    monkeypatch.setattr(module, "database_get", forbidden_database)

    async def scenario():
        async with Client(module.mcp) as client:
            result = await client.call_tool_mcp("resume_context", arguments)
            assert result.is_error is True
            assert result.structured_content["status_code"] == 400
            assert "positive integers" in result.structured_content["error"]
            wire = result.model_dump(by_alias=True)
            assert wire["isError"] is True
            assert wire["structuredContent"]["status_code"] == 400
    asyncio.run(scenario())


def test_mcp_stopped_database_is_structured_dependency_error(monkeypatch):
    # Close a real localhost listener so the database connection is refused.
    database = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = database.server_port
    database.server_close()
    module = load_module("mcp_test_stopped_database", SERVICE_DIR / "mcp_server.py")
    monkeypatch.setattr(module, "DATABASE_API_URL", f"http://127.0.0.1:{port}")

    async def scenario():
        async with Client(module.mcp) as client:
            result = await client.call_tool("resume_context", {"profile_id": 1, "resume_id": 1}, raise_on_error=False)
            assert result.is_error is True
            assert result.structured_content["status_code"] == 503
            assert "unavailable" in result.structured_content["error"]
            assert "candidate_profile" not in result.structured_content
    asyncio.run(scenario())


def test_resume_guidance_has_real_local_sources_and_correct_scores(rag):
    with rag.app.test_client() as client:
        result = client.post("/retrieve", json={"query": "resume Docker evidence", "feature": "resume"}).get_json()
    assert result["results"]
    assert "not a probability" in result["confidence_basis"]
    for document in result["results"]:
        source_file = SERVICE_DIR.parent / document["source_id"].removeprefix("repo://")
        assert source_file.is_file()
        assert " ".join(document["text"].split()) in " ".join(source_file.read_text().split())
        assert document["source"].startswith(document["source_id"] + "#chunk-")
        assert document["score"] > 0
        assert document["feature"] == "resume"


def test_no_match_is_low_confidence_without_sources(rag):
    with rag.app.test_client() as client:
        payload = client.post("/pipeline", json={"query": "xyzzzyy", "feature": "resume"}).get_json()
    assert payload["review"]["confidence"] == "low"
    assert payload["answer"]["sources"] == []
    assert payload["validate"] == {"grounded": False, "has_sources": False}


def test_default_retrieval_preserves_interview_corpus(rag):
    result = rag.retrieve("API interview")
    assert result["results"]
    assert all(document["source"].startswith("shared://interview/") for document in result["results"])


def test_student3_preserves_plain_structured_mcp_context(monkeypatch):
    backend = load_module("student3_context_regression", SERVICE_DIR.parent / "student-3" / "backend" / "app.py")
    expected = {"target_role": "Engineer", "evaluation_dimensions": ["clarity"]}

    async def mcp_result(*_args):
        return expected

    class RagResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [], "confidence": "low"}

    monkeypatch.setattr(backend, "AI_SERVICES_ENABLED", True)
    monkeypatch.setattr(backend, "call_mcp_tool", mcp_result)
    monkeypatch.setattr(backend.session, "post", lambda *args, **kwargs: RagResponse())
    context = backend.shared_ai_context(target_role="Engineer", interview_type="general", query="question")
    assert context["mcp"] == expected


@pytest.mark.parametrize("route", ["/retrieve", "/pipeline"])
@pytest.mark.parametrize("data", [
    {"query": ""}, {"query": "resume", "top_k": True}, {"query": "resume", "top_k": -1},
    {"query": "resume", "top_k": "3"}, {"query": "resume", "feature": []},
    {"query": "resume", "feature": "unknown"},
])
def test_both_rag_routes_reject_invalid_input(rag, route, data):
    with rag.app.test_client() as client:
        assert client.post(route, json=data).status_code == 400
