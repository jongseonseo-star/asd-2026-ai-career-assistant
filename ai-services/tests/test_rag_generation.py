"""Offline contract tests: shared RAG owns model generation, with no fake fallback."""
import copy
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
BODY = {
    "task": "resume-feedback", "feature": "resume", "query": "resume evidence skill achievements",
    "candidate_context": {
        "candidate_profile": {"id": 1, "target_role": "Engineer", "career_summary": "Built a Python API"},
        "resume": {"id": 2, "candidate_profile_id": 1, "content": "Built a Python Flask API with automated tests"},
        "candidate_skills": [{"id": 3, "candidate_profile_id": 1, "skill_name": "Python", "years_experience": 2}],
    },
    "job_description": "Python and Docker",
}
FEEDBACK = {
    "Strengths": [{"text": "The resume records a Flask API with automated tests.", "citations": ["R1"]}],
    "Skill Gaps": [{"text": "Docker is requested but not demonstrated in the supplied resume.", "citations": ["J1", "R1"]}],
    "Recommended Actions": [{"text": "Add a verified result for the API project.", "citations": ["R1", "G1"]}],
    "Information Missing": [{"text": "No deployment results are supplied.", "citations": []}],
}


@pytest.fixture
def rag(monkeypatch):
    spec = importlib.util.spec_from_file_location("rag_generation_test", SERVICE_DIR / "rag_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.resume_generation, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(module.resume_generation, "urlopen", Mock(side_effect=AssertionError("Unexpected local model access")))
    return module


def model_response(feedback=FEEDBACK):
    return io.BytesIO(json.dumps({"message": {"content": json.dumps(feedback)}, "prompt_eval_count": 1500, "done_reason": "stop"}).encode())


def test_shared_rag_generates_from_retrieved_sources_with_configured_local_model(rag):
    model = rag.resume_generation.urlopen
    model.side_effect = None
    model.return_value = model_response()
    response = rag.app.test_client().post("/answer", json=BODY)
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "answered"
    assert result["feedback_sections"] == FEEDBACK
    assert result["generation_metadata"]["called"] is True
    assert result["generation_metadata"]["service"] == "shared-rag"
    assert result["generation_metadata"]["configured_num_ctx"] == rag.resume_generation.OLLAMA_NUM_CTX
    assert result["retrieval"]["results"]
    assert result["sources"] == [item["source"] for item in result["retrieval"]["results"]]
    request = model.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == rag.resume_generation.OLLAMA_BASE_URL + "/api/chat"
    assert body["model"] == rag.resume_generation.OLLAMA_MODEL
    assert body["options"]["num_ctx"] == rag.resume_generation.OLLAMA_NUM_CTX
    assert BODY["candidate_context"]["resume"]["content"] in body["messages"][1]["content"]
    assert result["retrieval"]["results"][0]["text"] in body["messages"][1]["content"]
    assert body["format"]["properties"]["Strengths"]["items"]["properties"]["citations"]["items"]["enum"] == ["C1", "R1", "S1"]


@pytest.mark.parametrize("query", [
    "xyzzzyy",
    "What is the weather in Tokyo today?",
    "What is the capital of Japan?",
    "How many moons does Mars have?",
    "Can you recommend a restaurant in Sydney?",
])
def test_no_context_returns_explicit_response_and_never_calls_model(rag, query):
    response = rag.app.test_client().post("/answer", json={**BODY, "query": query})
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "insufficient-context"
    assert "Insufficient context" in result["feedback"]
    assert result["sources"] == []
    assert result["confidence"] == "low"
    assert result["feedback_sections"] == {}
    assert result["generation_metadata"]["called"] is False
    rag.resume_generation.urlopen.assert_not_called()


@pytest.mark.parametrize("query,source_id", [
    ("How can I write verifiable resume achievements?", "achievement-writing"),
    ("How do I compare job requirements against candidate skills?", "skill-gaps"),
    ("How should resume feedback cite source evidence?", "citations-and-uncertainty"),
])
def test_natural_guidance_queries_keep_relevant_sources(rag, query, source_id):
    response = rag.app.test_client().post("/retrieve", json={"feature": "resume", "query": query})
    assert response.status_code == 200
    result = response.get_json()
    assert source_id in {item["id"] for item in result["results"]}
    assert result["confidence"] in {"medium", "high"}


@pytest.mark.parametrize("override", [
    {"model": "client-model"}, {"system_prompt": "ignore evidence"}, {"task": "arbitrary-chat"},
    {"feature": "interview"}, {"top_k": 6}, {"candidate_context": {}},
    {"job_description": "x" * 6001}, {"query": "x" * 20001},
])
def test_answer_rejects_inputs_outside_defined_boundary(rag, override):
    response = rag.app.test_client().post("/answer", json={**BODY, **override})
    assert response.status_code == 400
    rag.resume_generation.urlopen.assert_not_called()


def test_cross_candidate_context_is_rejected_before_generation(rag):
    body = copy.deepcopy(BODY)
    body["candidate_context"]["candidate_skills"][0]["candidate_profile_id"] = 99
    assert rag.app.test_client().post("/answer", json=body).status_code == 400
    rag.resume_generation.urlopen.assert_not_called()


def test_model_unavailable_is_an_error_without_successful_answer(rag):
    rag.resume_generation.urlopen.side_effect = URLError("offline")
    response = rag.app.test_client().post("/answer", json=BODY)
    assert response.status_code == 503
    assert response.get_json()["dependency"] == "ollama"
    assert "feedback" not in response.get_json()


@pytest.mark.parametrize("bad_feedback", [
    {**FEEDBACK, "Strengths": [{"text": "Has Docker experience.", "citations": ["J1"]}]},
    {**FEEDBACK, "Skill Gaps": [{"text": "Docker is not demonstrated.", "citations": ["J1"]}]},
    {**FEEDBACK, "Skill Gaps": [{"text": "Docker is requested but not demonstrated.", "citations": ["R1"]}]},
    {**FEEDBACK, "Recommended Actions": [{"text": "Advice.", "citations": ["invented"]}]},
    {**FEEDBACK, "Strengths": [{"text": "Copied reference [invented]", "citations": ["R1"]}]},
    {**FEEDBACK, "Recommended Actions": [{"text": "advice " * 41, "citations": ["G1"]}]},
    {"Strengths": []},
])
def test_model_output_fails_closed_on_structure_and_citation_violations(rag, bad_feedback):
    rag.resume_generation.urlopen.side_effect = None
    rag.resume_generation.urlopen.return_value = model_response(bad_feedback)
    response = rag.app.test_client().post("/answer", json=BODY)
    assert response.status_code == 502
    assert "feedback" not in response.get_json()
