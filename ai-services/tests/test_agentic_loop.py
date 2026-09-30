"""Offline validator tests: fixtures never claim real model or deployment evidence."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError

import pytest


@pytest.fixture
def loop():
    path = Path(__file__).resolve().parents[1] / "agentic_loop.py"
    spec = importlib.util.spec_from_file_location("tested_agentic_loop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def candidate():
    return {
        "candidate_profile": {"id": 1, "target_role": "Engineer", "career_summary": "Built a Python API."},
        "resume": {"id": 2, "candidate_profile_id": 1, "content": "Built a Python API with tests."},
        "candidate_skills": [{"id": 3, "candidate_profile_id": 1, "skill_name": "Python"}],
        "sources": ["db://student-2/profiles/1", "db://student-2/resumes/2", "db://student-2/skills/3"],
    }


@pytest.fixture
def retrieval():
    return {"query": "resume", "feature": "resume", "confidence": "medium", "confidence_basis": "One matching guidance document.",
        "retrieval_mode": "vector", "vector_store_status": "ready", "embedding_dimensions": 256,
        "embedding_version": "fixture-embedding", "corpus_version": "fixture-version",
        "results": [{"id": "outcomes", "title": "Outcomes", "text": "State verified project outcomes.",
            "chunk_id": "resume:outcomes:1", "source_id": "repo://ai-services/knowledge/resume/outcomes.md",
            "corpus_version": "fixture-version", "authority_tier": "tier_3",
            "source": "repo://ai-services/knowledge/resume/outcomes.md", "feature": "resume", "score": 2}]}


@pytest.fixture
def answer(retrieval):
    return {"status": "answered", "feedback": "Feedback with source citations.", "confidence": "medium",
        "confidence_basis": retrieval["confidence_basis"], "model": "fixture-model", "generation_metadata": {"called": True},
        "retrieval": retrieval, "sources": [retrieval["results"][0]["source"]],
        "evidence_sources": [
            {"id": "R1", "kind": "candidate", "source": "db://student-2/resumes/2", "text": "Built a Python API with tests."},
            {"id": "J1", "kind": "requirement", "source": "request://job-description", "text": "Python and Docker."},
            {"id": "G1", "kind": "guidance", "source": retrieval["results"][0]["source"], "text": retrieval["results"][0]["text"]}],
        "feedback_sections": {
            "Strengths": [{"text": "The resume describes a tested Python API.", "citations": ["R1"]}],
            "Skill Gaps": [{"text": "Docker is requested but not demonstrated.", "citations": ["R1", "J1"]}],
            "Recommended Actions": [{"text": "Add verified project outcomes.", "citations": ["R1", "G1"]}],
            "Information Missing": [{"text": "Deployment evidence was not supplied.", "citations": []}]}}


@pytest.fixture
def empty_answer(retrieval):
    return {"status": "insufficient-context", "feedback": "Insufficient context: no relevant guidance was found.",
        "confidence": "low", "confidence_basis": "No retrieved guidance.", "sources": [], "feedback_sections": {},
        "generation_metadata": {"called": False},
        "retrieval": {**retrieval, "results": [], "feature": "resume", "confidence": "low", "confidence_basis": "No retrieved guidance."}}


@pytest.fixture
def corpus():
    return {"status": "success", "corpora": {"resume": {"feature": "resume", "stale": False,
        "embedding_dimensions": 256, "embedding_version": "fixture-embedding", "corpus_version": "fixture-version",
        "chunk_count": 4, "document_count": 4, "collection": "fixture-collection", "indexed_at": "fixture-time", "corpus_sha256": "fixture-hash"}}}


def mock_http(monkeypatch, loop, payload=None, raw=None):
    response = Mock(status=200)
    response.read.return_value = raw if raw is not None else json.dumps(payload).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    transport = Mock(return_value=response)
    monkeypatch.setattr(loop, "urlopen", transport)
    return transport


def mock_mcp(monkeypatch, candidate, *, tools=None, is_error=False):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.list_tools.return_value = tools if tools is not None else [SimpleNamespace(
        name="resume_context", inputSchema={"properties": {"profile_id": {"type": "integer"}, "resume_id": {"type": "integer"}}})]
    client.call_tool.return_value = SimpleNamespace(structured_content=candidate, is_error=is_error)
    factory = Mock(return_value=client)
    monkeypatch.setattr("fastmcp.Client", factory)
    return factory, client


def test_positive_answer_preserves_traceable_source_contract(loop, answer):
    assert loop.validate_answer(answer) == []


@pytest.mark.parametrize("mutation", [
    lambda a: a.update(confidence=[]),
    lambda a: a.update(confidence="high"),
    lambda a: a.update(generation_metadata={"called": False}),
    lambda a: a.update(sources=["repo://invented"]),
    lambda a: a.update(retrieval={"results": None}),
    lambda a: a["evidence_sources"][2].update(source="repo://invented"),
    lambda a: a["evidence_sources"][2].update(text="Invented guidance instead of retrieved text."),
    lambda a: a["feedback_sections"]["Strengths"][0].update(citations=["J1"]),
    lambda a: a["feedback_sections"]["Recommended Actions"][0].update(citations=["unknown"]),
    lambda a: a["feedback_sections"]["Skill Gaps"][0].update(citations=["J1"]),
    lambda a: a["feedback_sections"]["Skill Gaps"][0].update(citations=["R1"]),
    lambda a: a["feedback_sections"].update({"Skill Gaps": []}),
])
def test_http_success_cannot_hide_invalid_generated_payload(loop, answer, monkeypatch, mutation):
    mutation(answer)
    mock_http(monkeypatch, loop, answer)
    result = loop.check("http://fixture/answer", {}, validator=loop.validate_answer)
    assert result["status"] == 200
    assert result["passed"] is False
    assert result["validation_errors"]


def test_empty_context_is_valid_only_without_generation_or_claims(loop, empty_answer):
    assert loop.validate_answer(empty_answer, empty=True) == []
    empty_answer["generation_metadata"]["called"] = True
    assert loop.validate_answer(empty_answer, empty=True)
    empty_answer["generation_metadata"]["called"] = False
    empty_answer["feedback_sections"] = {"Strengths": [{"text": "Fabricated answer", "citations": []}]}
    assert loop.validate_answer(empty_answer, empty=True)


@pytest.mark.parametrize("payload", [None, [], {}, {"results": [], "confidence": []}, {"results": [None], "confidence": "high"}])
def test_malformed_retrieval_never_crashes_or_passes(loop, payload):
    assert loop.validate_retrieval(payload, "resume")
    assert loop.validate_answer(payload)


def test_mcp_records_actual_requested_tool_discovery_and_result(loop, candidate, monkeypatch):
    factory, client = mock_mcp(monkeypatch, candidate)
    result = asyncio.run(loop.check_mcp(base_url="http://fixture:9999", resume_id=2, timeout=7))
    assert result["passed"] is True
    factory.assert_called_once_with("http://fixture:9999/mcp", timeout=7)
    client.call_tool.assert_awaited_once_with("resume_context", arguments={"profile_id": 1, "resume_id": 2}, timeout=7)
    assert result["payload"]["sources"] == candidate["sources"]
    assert result["registered_tools"][0]["name"] == "resume_context"
    assert result["started_at"] and result["finished_at"]


@pytest.mark.parametrize("payload", [
    {"error": "Not found", "status_code": 404},
    {"candidate_profile": {"id": 1}, "resume": {"id": 2, "candidate_profile_id": 99}, "candidate_skills": []},
])
def test_mcp_application_error_does_not_pass_on_transport_success(loop, payload, monkeypatch):
    mock_mcp(monkeypatch, payload)
    result = asyncio.run(loop.check_mcp(resume_id=2))
    assert result["status"] == 200
    assert result["passed"] is False


def test_missing_mcp_tool_does_not_call_unknown_tool(loop, candidate, monkeypatch):
    _, client = mock_mcp(monkeypatch, candidate, tools=[])
    result = asyncio.run(loop.check_mcp(resume_id=2))
    assert result["passed"] is False
    client.call_tool.assert_not_called()


def test_mcp_rejects_boolean_id_and_missing_skill_sources(loop, candidate):
    candidate["candidate_profile"]["id"] = True
    assert loop.validate_mcp_payload(candidate, "resume", 1, 2, "Engineer")
    candidate["candidate_profile"]["id"] = 1
    candidate["sources"].pop()
    assert loop.validate_mcp_payload(candidate, "resume", 1, 2, "Engineer")


def test_mcp_timeout_is_bounded_and_saved_as_failure(loop, candidate, monkeypatch):
    _, client = mock_mcp(monkeypatch, candidate)

    async def stalled_discovery():
        await asyncio.sleep(10)

    client.list_tools.side_effect = stalled_discovery
    result = asyncio.run(loop.check_mcp(resume_id=2, timeout=0.01))
    assert result["passed"] is False
    assert "TimeoutError" in result["error"]
    assert result["duration_seconds"] < 1


def test_http_invalid_json_and_timeout_are_controlled(loop, monkeypatch):
    transport = mock_http(monkeypatch, loop, raw=b"<html>not JSON</html>")
    result = loop.check("http://fixture/retrieve", validator=loop.validate_answer, timeout=2)
    assert not result["passed"]
    transport.side_effect = TimeoutError("fixture timeout")
    result = loop.check("http://fixture/retrieve", validator=loop.validate_answer, timeout=2)
    assert not result["passed"]
    assert transport.call_args.kwargs["timeout"] == 2


def test_http_error_preserves_service_failure_payload(loop, monkeypatch):
    error = HTTPError("http://fixture/answer", 503, "offline", {}, io.BytesIO(b'{"error":"Ollama is unavailable"}'))
    monkeypatch.setattr(loop, "urlopen", Mock(side_effect=error))
    result = loop.check("http://fixture/answer", validator=loop.validate_answer)
    assert result["status"] == 503 and result["passed"] is False
    assert result["payload"]["error"] == "Ollama is unavailable"


def test_run_captures_each_rag_request_and_uses_configured_endpoints(loop, candidate, corpus, retrieval, answer, empty_answer, monkeypatch, tmp_path, capsys):
    for name, port in (("MCP", 18765), ("RAG", 18766), ("OLLAMA", 11435)):
        monkeypatch.setenv(name + "_BASE_URL", f"http://127.0.0.1:{port}")
    mcp = AsyncMock(return_value={"name": "mcp-tool-validation", "passed": True, "payload": candidate})
    monkeypatch.setattr(loop, "check_mcp", mcp)
    seen = []

    def transport(request, *, timeout):
        body = json.loads(request.data) if request.data else None
        seen.append((request.full_url, body, timeout))
        data = corpus if request.full_url.endswith("/corpus") else retrieval if request.full_url.endswith("/retrieve") else empty_answer if body["query"] == loop.NO_CONTEXT_QUERY else answer
        response = Mock(status=200)
        response.read.return_value = json.dumps(data).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    monkeypatch.setattr(loop, "urlopen", transport)
    output = tmp_path / "evidence" / "rag.json"
    assert loop.run("rag", str(output), resume_id=2, timeout=8, checks_only=True) == 0
    evidence = json.loads(output.read_text())
    assert evidence["review"]["passed"] is True
    assert len(evidence["checks"]) == 5
    assert evidence["checks"][2]["request"]["body"] == {"query": "resume skills evidence outcomes", "feature": "resume", "top_k": 3}
    assert [url for url, _, _ in seen] == ["http://127.0.0.1:18766/corpus", "http://127.0.0.1:18766/retrieve", "http://127.0.0.1:18766/answer", "http://127.0.0.1:18766/answer"]
    assert seen[2][1]["candidate_context"] == candidate
    assert seen[3][1]["query"] == loop.NO_CONTEXT_QUERY
    assert all(timeout == 8 for _, _, timeout in seen)
    assert mcp.call_args.kwargs["base_url"] == "http://127.0.0.1:18765"
    assert set(mcp.call_args.kwargs["required_tools"]) == {"refresh_corpus", "retrieve_context", "answer_question"}
    assert json.loads(capsys.readouterr().out) == evidence


def test_failed_payload_sets_nonzero_exit_and_preserves_evidence(loop, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(loop, "check_mcp", AsyncMock(return_value={"passed": False, "status": 200, "validation_errors": ["wrong profile"]}))
    output = tmp_path / "failed.json"
    assert loop.run("mcp", str(output), checks_only=True) == 1
    assert json.loads(output.read_text())["review"]["passed"] is False


def test_interview_rag_cannot_falsely_pass_extract_only_pipeline(loop, monkeypatch, capsys):
    transport = Mock(side_effect=AssertionError("No unsupported generation request expected"))
    monkeypatch.setattr(loop, "urlopen", transport)
    assert loop.run("rag", feature="interview", checks_only=True) == 1
    evidence = json.loads(capsys.readouterr().out)
    assert "Interview RAG generation is not validated" in evidence["checks"][0]["validation_errors"][0]
    transport.assert_not_called()


def test_release0_runs_all_four_legacy_modes_and_cannot_hide_one_failure(loop, monkeypatch, capsys):
    captured = Mock(side_effect=lambda mode, **kw: {
        "mode": mode, "review": {"passed": mode != "devops", "checks_passed": mode != "devops"}})
    monkeypatch.setattr(loop, "capture_mode", captured)
    assert loop.run("release0", checks_only=True) == 1
    evidence = json.loads(capsys.readouterr().out)
    assert list(evidence["mode_results"]) == ["db", "endpoints", "architecture", "devops"]
    assert [call.args[0] for call in captured.call_args_list] == list(evidence["mode_results"])
    assert evidence["human_decision"]["status"] == "pending"


def test_normal_mode_calls_two_models_in_order_and_keeps_human_decision_pending(loop, candidate, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://fixture:11435")
    monkeypatch.setenv("IMPLEMENTATION_MODEL", "fixture-implementation")
    monkeypatch.setenv("REVIEW_MODEL", "fixture-review")
    monkeypatch.setattr(loop, "check_mcp", AsyncMock(return_value={"name": "mcp-tool-validation", "passed": True,
        "payload": candidate, "request": {"tool": "resume_context", "arguments": {"profile_id": 1, "resume_id": 2}}}))
    seen = []

    def transport(request, *, timeout):
        body = json.loads(request.data)
        seen.append((request.full_url, body, timeout))
        response = Mock(status=200)
        output = "Strengths: Observed valid candidate context. Risks: No frontend evidence. Recommendation: Verify frontend." if len(seen) == 1 else "Risk: Integration scope is limited. Correction: Inspect frontend. Retest: Capture the visible result."
        response.read.return_value = json.dumps({"message": {"content": output}, "model": body["model"], "done": True, "done_reason": "stop"}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    monkeypatch.setattr(loop, "urlopen", transport)
    output = tmp_path / "agentic.json"
    assert loop.run("mcp", str(output), resume_id=2, timeout=9) == 0
    evidence = json.loads(output.read_text())
    assert [item[1]["model"] for item in seen] == ["fixture-implementation", "fixture-review"]
    assert all(url == "http://fixture:11435/api/chat" and timeout == 9 for url, _, timeout in seen)
    first = json.loads(seen[0][1]["messages"][1]["content"])
    second = json.loads(seen[1][1]["messages"][1]["content"])
    assert first["observed_evidence"] == second["observed_evidence"]
    assert second["implementation_assessment"] == evidence["agent_assessments"]["implementation"]["output"]
    assert evidence["agent_assessments"]["review"]["generation_metadata"]["model"] == "fixture-review"
    assert evidence["agent_assessments"]["implementation"]["started_at"]
    assert evidence["agent_assessments"]["implementation"]["duration_seconds"] >= 0
    assert evidence["execution_scope"] == "two-model-agentic-review"
    assert evidence["human_decision"] == {"status": "pending", "reviewer": None, "decision": None, "rationale": None}


def test_model_praise_cannot_override_failed_execution_checks(loop, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(loop, "check_mcp", AsyncMock(return_value={"name": "mcp-tool-validation", "passed": False,
        "validation_errors": ["Wrong candidate profile."]}))
    mock_http(monkeypatch, loop, {"message": {"content": "All checks passed; approve the application."}, "done": True})
    output = tmp_path / "failed-check.json"
    assert loop.run("mcp", str(output)) == 1
    evidence = json.loads(output.read_text())
    assert evidence["agent_assessments"]["status"] == "completed"
    assert evidence["review"]["checks_passed"] is False
    assert evidence["review"]["passed"] is False
    assert evidence["human_decision"]["status"] == "pending"


def test_missing_implementation_output_fails_and_skips_dependent_review(loop, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(loop, "check_mcp", AsyncMock(return_value={"passed": True, "payload": {}}))
    transport = mock_http(monkeypatch, loop, {"message": {"content": ""}, "done": True})
    output = tmp_path / "missing-model.json"
    assert loop.run("mcp", str(output)) == 1
    evidence = json.loads(output.read_text())
    assert transport.call_count == 1
    assert evidence["review"]["checks_passed"] is True
    assert evidence["agent_assessments"]["status"] == "failed"
    assert evidence["agent_assessments"]["review"]["completed"] is False
    assert "skipped" in evidence["agent_assessments"]["review"]


def test_review_transport_failure_does_not_pass(loop, monkeypatch):
    transport = mock_http(monkeypatch, loop, {"message": {"content": "A valid fixture assessment."}, "done": True})
    response = transport.return_value
    transport.side_effect = [response, TimeoutError("fixture timeout")]
    assessments = loop.assess_checks("mcp", "resume", [{"passed": True}], base_url="http://fixture", timeout=3)
    assert assessments["status"] == "failed"
    assert assessments["implementation"]["completed"] is True
    assert assessments["review"]["completed"] is False
    assert "TimeoutError" in assessments["review"]["error"]
    assert transport.call_args.kwargs["timeout"] == 3


def test_checks_only_explicitly_skips_models(loop, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(loop, "check_mcp", AsyncMock(return_value={"passed": True, "payload": {}}))
    transport = Mock(side_effect=AssertionError("Checks-only must not call a model."))
    monkeypatch.setattr(loop, "urlopen", transport)
    output = tmp_path / "checks-only.json"
    assert loop.run("mcp", str(output), checks_only=True) == 0
    evidence = json.loads(output.read_text())
    assert evidence["execution_scope"] == "checks-only"
    assert evidence["agent_assessments"]["status"] == "skipped"
    assert "not a full agentic review" in evidence["agent_assessments"]["reason"]
    transport.assert_not_called()


def test_assessment_excerpts_are_explicit_and_do_not_change_execution_evidence(loop):
    checks = [{"passed": True, "payload": {"content": "x" * 30000}, "request": {"body": {"query": "q" * 20000}}}]
    observed = loop.assessment_evidence("rag", "resume", checks)
    assert observed["checks"][0]["result_truncated"] is True
    assert observed["checks"][0]["request"]["query_truncated"] is True
    assert len(observed["checks"][0]["result_excerpt"]) <= 16000
    assert len(observed["checks_sha256"]) == 64
    assert len(checks[0]["payload"]["content"]) == 30000


def test_rag_assessment_preserves_candidate_facts_and_every_claim_citation(loop, candidate, answer):
    checks = [{"name": "mcp", "passed": True, "payload": candidate},
              {"name": "answer", "passed": True, "payload": answer,
               "request": {"body": {"candidate_context": candidate, "query": "resume"}}}]
    observed = loop.assessment_evidence("rag", "resume", checks)
    assert observed["candidate_contexts"] == [candidate]
    reviewed = observed["checks"][1]["answer"]
    assert reviewed["claims_by_section"] == answer["feedback_sections"]
    for source in answer["evidence_sources"]:
        document = observed["documents_by_hash"][reviewed["citation_id_to_document"][source["id"]]]
        assert document["source"] == source["source"]
        assert document["text"] == source["text"]


@pytest.mark.parametrize("mode,calls", [("db", 1), ("endpoints", 1), ("architecture", 2), ("devops", 2), ("mcp", 2), ("rag", 2)])
def test_course_model_roles_and_external_prompts(loop, monkeypatch, mode, calls):
    transport = mock_http(monkeypatch, loop, {"message": {"content": "Evidence requires human inspection."}, "done": True})
    result = loop.assess_checks(mode, "resume", [{"passed": True}], base_url="http://fixture", timeout=3)
    assert result["status"] == "completed"
    assert transport.call_count == calls
    assert result["implementation"]["prompt_paths"]
    if mode == "rag":
        assert any(path.endswith("rag_reasoning.txt") for path in result["review"]["prompt_paths"])


def test_oversized_candidate_facts_fail_instead_of_silent_truncation(loop, candidate, monkeypatch):
    candidate["resume"]["content"] = "Important fact. " * 3000
    transport = Mock(side_effect=AssertionError("Oversized evidence must not be sent to a model."))
    monkeypatch.setattr(loop, "urlopen", transport)
    result = loop.assess_checks("mcp", "resume", [{"passed": True, "payload": candidate}], base_url="http://fixture", timeout=3)
    assert result["status"] == "failed"
    assert "not truncated" in result["error"]
    assert result["observed_evidence"]["candidate_contexts"][0]["resume"] == candidate["resume"]
    transport.assert_not_called()


def test_expected_input_rejection_is_evidence_but_wrong_status_fails(loop, monkeypatch):
    transport = Mock(side_effect=HTTPError("http://fixture", 400, "Bad Request", {}, io.BytesIO(b'{"error":"required"}')))
    monkeypatch.setattr(loop, "urlopen", transport)
    result = loop.check("http://fixture", {}, expected_status=400, validator=lambda p: [] if p.get("error") else ["missing error"])
    assert result["passed"] is True
    assert result["status"] == 400
    mock_http(monkeypatch, loop, {"id": 1})
    assert loop.check("http://fixture", {}, expected_status=400, validator=lambda p: [])["passed"] is False


def test_missing_external_prompt_fails_instead_of_silently_using_a_default(loop, monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "PROMPT_DIR", tmp_path)
    result = loop.assess_checks("db", "resume", [{"passed": True}], base_url="http://fixture", timeout=3)
    assert result["status"] == "failed"
    assert "prompt unavailable" in result["error"]


def test_token_truncated_model_assessment_is_not_complete(loop, monkeypatch):
    transport = mock_http(monkeypatch, loop, {"message": {"content": "Partial assessment"}, "done": True, "done_reason": "length"})
    result = loop.assess_checks("mcp", "resume", [{"passed": True}], base_url="http://fixture", timeout=3)
    assert result["status"] == "failed"
    assert transport.call_count == 1
    assert result["implementation"]["raw_output"] == "Partial assessment"
    assert result["implementation"]["generation_metadata"]["done_reason"] == "length"


def test_legacy_assessment_has_domain_facts_without_candidate_context_boilerplate(loop):
    checks = [{"name": "endpoint-nfr-20-samples", "passed": True, "payload": {
        "target_ms": 500, "required": 19, "within_target": 20,
        "samples": [{"passed": True, "duration_seconds": .02} for _ in range(20)]}}]
    observed = loop.assessment_evidence("endpoints", "resume", checks)
    facts = observed["checks"][0]["observed"]
    assert facts["durations_ms"] == [20] * 20
    assert facts["within_target"] == 20
    assert "candidate_contexts" not in observed
    assert "sample_count" in facts and "samples" not in facts


def test_stale_or_missing_corpus_and_degraded_retrieval_never_pass(loop, corpus, retrieval):
    assert loop.validate_corpus(corpus, "resume") == []
    assert loop.validate_corpus(corpus, "interview")
    corpus["corpora"]["resume"]["stale"] = True
    assert loop.validate_corpus(corpus, "resume")
    assert loop.validate_retrieval(retrieval, "resume", corpus_version="another-version")
    retrieval["retrieval_mode"] = "lexical_fallback"
    assert loop.validate_retrieval(retrieval, "resume")


def test_rag_discovery_requires_all_three_registered_tools(loop, candidate, monkeypatch):
    mock_mcp(monkeypatch, candidate)
    result = asyncio.run(loop.check_mcp(resume_id=2, required_tools=("refresh_corpus", "retrieve_context", "answer_question")))
    assert result["passed"] is False
    assert "not registered" in result["validation_errors"][0]
