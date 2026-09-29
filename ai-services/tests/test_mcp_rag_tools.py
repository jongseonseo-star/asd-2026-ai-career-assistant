"""Real MCP protocol and fixture HTTP services; no local model is invoked."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread

from fastmcp import Client
import pytest


@pytest.fixture
def services(monkeypatch):
    state = {"seen": [], "rag_status": 200, "rag_payload": None, "foreign_resume": False}

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            state["seen"].append((self.path, None))
            records = {
                "/api/v1/profiles/1": {"id": 1, "target_role": "Engineer"},
                "/api/v1/resumes/1": {"id": 1, "candidate_profile_id": 2 if state["foreign_resume"] else 1, "content": "A Python API project"},
                "/api/v1/skills?candidate_profile_id=1": [{"id": 1, "candidate_profile_id": 1, "skill_name": "Python"}],
            }
            self.send(200 if self.path in records else 404, records.get(self.path, {"error": "Not found"}))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["seen"].append((self.path, body))
            payload = state["rag_payload"]
            if payload is None:
                payload = {
                    "/refresh": {"status": "success", "corpora": [{"feature": body.get("feature"), "chunk_count": 4}]},
                    "/retrieve": {"feature": body.get("feature"), "query": body.get("query"), "results": [{"id": "fixture", "text": "Cite evidence", "source": "repo://fixture"}], "confidence": "medium"},
                    "/answer": {"status": "answered", "feedback": "Fixture response, not live inference", "confidence": "medium", "sources": ["repo://fixture"]},
                }[self.path]
            self.send(state["rag_status"], payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = Path(__file__).resolve().parents[1] / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("mcp_rag_tools_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for setting in ("DATABASE_API_URL", "RAG_BASE_URL"):
        monkeypatch.setattr(module, setting, f"http://127.0.0.1:{server.server_port}")
    yield module, state
    server.shutdown()
    server.server_close()
    thread.join()


def call(module, tool, arguments):
    async def request():
        async with Client(module.mcp) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)
    return asyncio.run(request())


def test_registered_rag_tools_have_bounded_inputs(services):
    module, _ = services

    async def scenario():
        async with Client(module.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert {"resume_context", "interview_context", "refresh_corpus", "retrieve_context", "answer_question"} <= set(tools)
            schema = tools["retrieve_context"].input_schema
            assert schema["additionalProperties"] is False
            assert schema["properties"]["top_k"]["minimum"] == 1
            assert schema["properties"]["top_k"]["maximum"] == 5
            assert schema["properties"]["feature"]["enum"] == ["resume", "interview", "jobs"]
            assert schema["properties"]["query"]["maxLength"] == 20000
    asyncio.run(scenario())


def test_refresh_and_retrieval_use_only_configured_rag_routes(services):
    module, state = services
    refreshed = call(module, "refresh_corpus", {"feature": "resume"})
    retrieved = call(module, "retrieve_context", {"query": " STAR interview ", "top_k": 2, "feature": "interview"})
    assert refreshed.is_error is False
    assert retrieved.is_error is False
    assert retrieved.structured_content["confidence"] == "medium"
    assert state["seen"] == [("/refresh", {"feature": "resume"}),
                             ("/retrieve", {"feature": "interview", "query": "STAR interview", "top_k": 2})]


def test_answer_fetches_owned_live_database_context_before_rag(services):
    module, state = services
    result = call(module, "answer_question", {"profile_id": 1, "resume_id": 1, "query": "resume evidence", "job_description": "Python and Docker"})
    assert result.is_error is False
    assert result.structured_content["status"] == "answered"
    assert [path for path, _ in state["seen"]] == ["/api/v1/profiles/1", "/api/v1/resumes/1", "/api/v1/skills?candidate_profile_id=1", "/answer"]
    body = state["seen"][-1][1]
    assert body["task"] == "resume-feedback" and body["feature"] == "resume"
    assert body["candidate_context"]["resume"]["content"] == "A Python API project"
    assert body["job_description"] == "Python and Docker"


def test_answer_preserves_insufficient_context_without_fabricated_answer(services):
    module, state = services
    state["rag_payload"] = {"status": "insufficient-context", "feedback": "Insufficient context", "confidence": "low", "sources": [], "generation_metadata": {"called": False}}
    result = call(module, "answer_question", {"profile_id": 1, "resume_id": 1, "query": "unrelated weather"})
    assert result.is_error is False
    assert result.structured_content == state["rag_payload"]


def test_foreign_resume_stops_before_rag(services):
    module, state = services
    state["foreign_resume"] = True
    result = call(module, "answer_question", {"profile_id": 1, "resume_id": 1, "query": "resume"})
    assert result.is_error is True
    assert result.structured_content["status_code"] == 400
    assert "/answer" not in [path for path, _ in state["seen"]]


@pytest.mark.parametrize("tool,arguments", [
    ("refresh_corpus", {"feature": "arbitrary-folder"}),
    ("retrieve_context", {"query": "resume", "top_k": 6}),
    ("retrieve_context", {"query": "resume", "top_k": True}),
    ("retrieve_context", {"query": "   "}),
    ("retrieve_context", {"query": "x" * 20001}),
    ("retrieve_context", {"query": "resume", "url": "http://untrusted.example"}),
    ("answer_question", {"profile_id": 1, "resume_id": 1, "query": "resume", "candidate_context": {}}),
    ("answer_question", {"profile_id": 1, "resume_id": 1, "query": "resume", "model": "caller-model"}),
    ("answer_question", {"profile_id": 1, "resume_id": 1, "query": "resume", "job_description": "x" * 6001}),
])
def test_invalid_tool_inputs_do_not_reach_http_services(services, tool, arguments):
    module, state = services
    result = call(module, tool, arguments)
    assert result.is_error is True
    assert result.structured_content["status_code"] == 400
    assert state["seen"] == []


@pytest.mark.parametrize("http_status,payload,expected", [
    (503, {"error": "Corpus unavailable"}, 503),
    (400, {"error": "Invalid query"}, 400),
    (200, {}, 502),
    (200, {"error": "Hidden failure"}, 502),
])
def test_rag_failures_are_real_mcp_tool_errors(services, http_status, payload, expected):
    module, state = services
    state.update(rag_status=http_status, rag_payload=payload)
    result = call(module, "retrieve_context", {"query": "resume"})
    assert result.is_error is True
    assert result.structured_content["status_code"] == expected
