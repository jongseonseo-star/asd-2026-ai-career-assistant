"""Tests for job analysis and human review."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "student-4/backend", ROOT / "ai-services"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def services():
    return {
        "shared": load("jobs_multi_agent_shared_test", "ai-services/multi_agent_server.py"),
        "backend": load("jobs_multi_agent_backend_test", "student-4/backend/app.py"),
        "frontend": load("jobs_multi_agent_frontend_test", "student-4/frontend/app.py"),
    }


@pytest.fixture(autouse=True)
def isolate_job_review_state(services, monkeypatch, tmp_path):
    workflow = services["shared"].job_multi_agent
    monkeypatch.setattr(workflow, "AUDIT_PATH", tmp_path / "multi-agent-jobs.jsonl")
    workflow.runs.clear()
    yield
    workflow.runs.clear()


@pytest.fixture
def context():
    return {
        "job": {"id": 1, "company_id": 2, "title": "Developer", "description": "Build Python APIs"},
        "company": {"id": 2, "name": "Example"},
        "skills": [{"id": 3, "job_posting_id": 1, "skill_name": "Python", "importance": "required"}],
        "sources": ["db://student-4/job_postings/1", "db://student-4/companies/2", "db://student-4/job_skills/3"],
    }


@pytest.fixture
def stages(context):
    return [
        {"steps": ["Read the selected posting", "Explain its skills"],
         "evidence_requirements": context["sources"], "approval_checkpoints": ["Reviewer audit", "Human decision"]},
        {"claims": [{"text": "The posting lists Python as required.", "sources": [context["sources"][2]]}]},
        {"verdict": "approved", "risk": "Check the answer against the posting.",
         "recommend_corrections": [], "suggest_retests": ["Verify the cited skill record."]},
    ]


def create_run(shared, monkeypatch, context, stages):
    model = Mock(side_effect=[json.dumps(stage) for stage in stages])
    monkeypatch.setattr(shared, "call_ollama", model)
    response = shared.app.test_client().post("/jobs/analyse", json={"query": "Explain the required skills", "job_context": context})
    return response, model


@pytest.fixture
def run(services, monkeypatch, context, stages):
    response, _ = create_run(services["shared"], monkeypatch, context, stages)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_job_stages_preserve_evidence_and_leave_human_decision_pending(services, monkeypatch, context, stages):
    response, model = create_run(services["shared"], monkeypatch, context, stages)
    assert response.status_code == 200
    result = response.get_json()
    UUID(result["run_id"])
    assert result["job_id"] == 1 and result["job_context"] == context
    assert result["query"] == "Explain the required skills"
    assert result["plan"] == stages[0] and result["work"] == stages[1] and result["review"] == stages[2]
    assert result["status"] == "awaiting-human-review" and result["iterations"] == 1
    assert result["human_decision"] == {
        "required": True, "status": "pending", "available_decisions": ["Accept", "Partially Accept", "Reject"],
        "decision": None, "reason": None, "evidence_used": None,
    }
    assert model.call_count == 3
    assert {entry["agent"] for entry in result["trajectory"]} >= {"Planner", "Worker", "Reviewer"}
    assert all(entry["stage"] and entry["timestamp"] and "output" in entry for entry in result["trajectory"])
    # Each downstream model needs the selected evidence, rather than a model-authored summary of it.
    for call in model.call_args_list:
        assert "db://student-4/job_skills/3" in str(call)
        assert context["job"]["description"] in str(call)


@pytest.mark.parametrize("final_verdict", ["approved", "needs_revision"])
def test_reviewer_feedback_reaches_worker_without_forcing_final_approval(services, monkeypatch, context, stages, final_verdict):
    revision = {"verdict": "needs_revision", "risk": "The skill explanation needs detail.",
                "recommend_corrections": ["Explain why the cited Python skill matters."], "suggest_retests": ["Recheck the citation."]}
    final_review = {**revision, "verdict": final_verdict}
    response, model = create_run(services["shared"], monkeypatch, context, [stages[0], stages[1], revision, stages[1], final_review])
    assert response.status_code == 200
    result = response.get_json()
    assert model.call_count == 5 and result["iterations"] == 2
    assert revision["recommend_corrections"][0] in str(model.call_args_list[3])
    assert result["review"]["verdict"] == final_verdict
    assert result["status"] == "awaiting-human-review"
    assert result["human_decision"]["decision"] is None


@pytest.mark.parametrize("bad_stage, expected", [(None, 503), ("not JSON", 502)])
@pytest.mark.parametrize("stage_index", [0, 1, 2])
def test_job_model_failure_is_not_replaced_with_successful_fallback(services, monkeypatch, context, stages, bad_stage, expected, stage_index):
    shared = services["shared"]
    responses = [json.dumps(stage) for stage in stages]
    responses[stage_index] = bad_stage
    model = Mock(side_effect=responses)
    monkeypatch.setattr(shared, "call_ollama", model)
    response = shared.app.test_client().post("/jobs/analyse", json={"query": "Skills", "job_context": context})
    assert response.status_code == expected
    assert "run_id" not in response.get_json()


def test_unknown_worker_sources_are_rejected_before_reviewer(services, monkeypatch, context, stages):
    stages[1]["claims"][0]["sources"] = ["db://student-4/job_postings/99"]
    response, model = create_run(services["shared"], monkeypatch, context, stages)
    assert response.status_code == 502
    assert model.call_count == 2


@pytest.mark.parametrize("case", ["blank-query", "long-query", "foreign-company", "foreign-skill", "missing-sources"])
def test_invalid_job_inputs_never_reach_models(services, monkeypatch, context, case):
    shared = services["shared"]
    body = {"query": "Skills", "job_context": context}
    if case == "blank-query":
        body["query"] = " "
    elif case == "long-query":
        body["query"] = "x" * 2001
    elif case == "foreign-company":
        context["company"]["id"] = 99
    elif case == "foreign-skill":
        context["skills"][0]["job_posting_id"] = 99
    else:
        context["sources"] = []
    model = Mock(side_effect=AssertionError("Invalid input must not call a model"))
    monkeypatch.setattr(shared, "call_ollama", model)
    response = shared.app.test_client().post("/jobs/analyse", json=body)
    assert response.status_code == 400
    model.assert_not_called()


@pytest.mark.parametrize("decision", ["Accept", "Partially Accept", "Reject"])
def test_human_decision_requires_written_evidence_and_cannot_be_overwritten(services, run, decision):
    client = services["shared"].app.test_client()
    path = f"/jobs/1/runs/{run['run_id']}/decision"
    evidence = "Compared the claim with job_skills/3 and the selected posting."
    assert client.post(path, json={"decision": "Accept"}).status_code == 400
    recorded = client.post(path, json={"decision": decision, "reason": "Reviewed the claim against the selected posting.", "evidence_used": evidence})
    assert recorded.status_code == 200
    result = recorded.get_json()
    assert result["status"] == "completed"
    assert result["human_decision"]["status"] == "recorded"
    assert result["human_decision"]["decision"] == decision
    assert result["human_decision"]["evidence_used"] == evidence
    assert client.post(path, json={"decision": "Accept", "reason": "Changed my mind", "evidence_used": evidence}).status_code == 409
    assert client.post(f"/jobs/2/runs/{run['run_id']}/decision", json={"decision": "Accept", "reason": "Checked", "evidence_used": evidence}).status_code == 404
    assert client.post(f"/jobs/1/runs/{uuid4()}/decision", json={"decision": "Accept", "reason": "Checked", "evidence_used": evidence}).status_code == 404
    audit = [json.loads(line) for line in services["shared"].job_multi_agent.AUDIT_PATH.read_text().splitlines()]
    assert len(audit) == 2
    assert audit[0]["human_decision"]["decision"] is None
    assert audit[1]["human_decision"]["decision"] == decision


@pytest.fixture
def backend(services, monkeypatch):
    backend = services["backend"]
    for name in ("AI_SERVICES_ENABLED", "MULTI_AGENT_ENABLED", "OLLAMA_ENABLED"):
        monkeypatch.setattr(backend, name, True)
    return backend


@pytest.mark.parametrize("flag", ["AI_SERVICES_ENABLED", "MULTI_AGENT_ENABLED", "OLLAMA_ENABLED"])
def test_each_cloud_disable_flag_blocks_analysis_and_decision_without_network(backend, monkeypatch, flag):
    monkeypatch.setattr(backend, flag, False)
    read = Mock(side_effect=AssertionError("Disabled analysis must not read MCP"))
    network = Mock(side_effect=AssertionError("Disabled analysis must not contact a service"))
    monkeypatch.setattr(backend, "mcp_job", read)
    monkeypatch.setattr(backend.session, "request", network)
    client = backend.app.test_client()
    assert client.post("/api/v1/multi-agent/jobs/1/analyse", json={"query": "Skills"}).status_code == 503
    assert client.post(f"/api/v1/multi-agent/jobs/1/runs/{uuid4()}/decision", json={
        "decision": "Accept", "reason": "Checked", "evidence_used": "Posting and skill record",
    }).status_code == 503
    read.assert_not_called()
    network.assert_not_called()


def test_backend_reads_selected_job_via_mcp_and_passes_only_owned_context(backend, monkeypatch, context, run):
    read = Mock(return_value=context)
    post = Mock(return_value=Mock(ok=True, status_code=200, json=lambda: run))
    monkeypatch.setattr(backend, "mcp_job", read)
    monkeypatch.setattr(backend.session, "post", post)
    response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": run["query"]})
    assert response.status_code == 200
    read.assert_called_once_with(1)
    post.assert_called_once()
    assert post.call_args.args[0].endswith("/jobs/analyse")
    assert post.call_args.kwargs["json"] == {"query": run["query"], "job_context": context}
    assert response.get_json()["human_decision"]["decision"] is None


@pytest.mark.parametrize("change", ["job-id", "context", "unknown-citation"])
def test_backend_revalidates_multi_agent_evidence(backend, monkeypatch, context, run, change):
    payload = copy.deepcopy(run)
    if change == "job-id":
        payload["job_id"] = 99
    elif change == "context":
        payload["job_context"]["job"]["description"] = "A different job description"
    else:
        payload["work"]["claims"][0]["sources"] = ["db://student-4/job_postings/99"]
    monkeypatch.setattr(backend, "mcp_job", Mock(return_value=context))
    monkeypatch.setattr(backend.session, "post", Mock(return_value=Mock(ok=True, status_code=200, json=lambda: payload)))
    response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": run["query"]})
    assert response.status_code == 502


def test_backend_cannot_accept_client_supplied_job_context(backend, monkeypatch, context):
    read = Mock()
    monkeypatch.setattr(backend, "mcp_job", read)
    response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": "Skills", "job_context": context})
    assert response.status_code == 400
    read.assert_not_called()


def test_backend_reports_shared_service_timeout(backend, monkeypatch, context):
    monkeypatch.setattr(backend, "mcp_job", Mock(return_value=context))
    monkeypatch.setattr(backend.session, "post", Mock(side_effect=requests.Timeout("Timed out")))
    response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": "Skills"})
    assert response.status_code == 503


def test_backend_rejects_automatic_human_approval_during_analysis(backend, monkeypatch, context, run):
    monkeypatch.setattr(backend, "mcp_job", Mock(return_value=context))
    for status, human_status in (("awaiting-human-review", "pending"), ("completed", "recorded")):
        payload = copy.deepcopy(run)
        payload["status"] = status
        payload["human_decision"].update(status=human_status, decision="Accept", reason="Automatic approval", evidence_used="Agent output")
        monkeypatch.setattr(backend.session, "post", Mock(return_value=Mock(ok=True, status_code=200, json=Mock(return_value=payload))))
        response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": run["query"]})
        assert response.status_code == 502, status


def test_decision_proxy_matches_the_requested_run_and_each_human_field(backend, monkeypatch, run):
    submitted = {"decision": "Partially Accept", "reason": "  Checked the posting.  ", "evidence_used": "  job_skills/3  "}
    recorded = copy.deepcopy(run)
    recorded["status"] = "completed"
    recorded["human_decision"].update(status="recorded", **{key: value.strip() for key, value in submitted.items()})
    post = Mock(return_value=Mock(ok=True, status_code=200, json=lambda: recorded))
    monkeypatch.setattr(backend.session, "post", post)
    client = backend.app.test_client()
    path = f"/api/v1/multi-agent/jobs/1/runs/{run['run_id']}/decision"
    response = client.post(path, json=submitted)
    assert response.status_code == 200
    assert post.call_args.args[0].endswith(f"/jobs/1/runs/{run['run_id']}/decision")
    assert post.call_args.kwargs["json"] == submitted
    for field in ("run_id", "decision", "reason", "evidence_used"):
        changed = copy.deepcopy(recorded)
        if field == "run_id":
            changed[field] = str(uuid4())
        else:
            changed["human_decision"][field] = "Reject" if field == "decision" else "A different submitted review"
        post.return_value.json = Mock(return_value=changed)
        assert client.post(path, json=submitted).status_code == 502, field


def test_malformed_request_types_return_400_without_model_calls(services, backend, monkeypatch, run):
    shared = services["shared"]
    model = Mock(side_effect=AssertionError("Malformed input must not call a model"))
    monkeypatch.setattr(shared, "call_ollama", model)
    for body in ([], {"query": [], "job_context": {}}, {"query": "Skills", "job_context": []}):
        assert shared.app.test_client().post("/jobs/analyse", json=body).status_code == 400
    invalid_decisions = (
        [],
        {"decision": ["Accept"], "reason": "Checked", "evidence_used": "Posting"},
        {"decision": "Accept", "reason": {}, "evidence_used": "Posting"},
        {"decision": "Accept", "reason": "Checked", "evidence_used": False},
    )
    network = Mock(side_effect=AssertionError("Malformed input must not contact a service"))
    monkeypatch.setattr(backend.session, "request", network)
    for body in invalid_decisions:
        assert shared.app.test_client().post(f"/jobs/1/runs/{run['run_id']}/decision", json=body).status_code == 400
        assert backend.app.test_client().post(f"/api/v1/multi-agent/jobs/1/runs/{run['run_id']}/decision", json=body).status_code == 400
    model.assert_not_called()
    network.assert_not_called()


def test_malformed_shared_result_types_return_502(backend, monkeypatch, context, run):
    monkeypatch.setattr(backend, "mcp_job", Mock(return_value=context))
    payloads = [[], {**run, "run_id": None}, {**run, "human_decision": []}, {**run, "work": []},
                {**run, "trajectory": ["not an agent event"]}, {**run, "iterations": True}]
    for payload in payloads:
        monkeypatch.setattr(backend.session, "post", Mock(return_value=Mock(ok=True, status_code=200, json=Mock(return_value=payload))))
        response = backend.app.test_client().post("/api/v1/multi-agent/jobs/1/analyse", json={"query": run["query"]})
        assert response.status_code == 502


def test_frontend_escapes_agent_output_and_sends_explicit_human_fields(services, monkeypatch, run):
    frontend = services["frontend"]
    payload = copy.deepcopy(run)
    unsafe = "<script>window.jobAgentUnsafe=true</script>"
    payload["work"]["claims"][0]["text"] = unsafe
    api = Mock(return_value=Mock(ok=True, status_code=200, json=lambda: payload))
    monkeypatch.setattr(frontend, "api", api)
    client = frontend.app.test_client()
    response = client.post("/multi-agent/jobs/1/analyse", data={"query": "Skills"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert unsafe not in html and "jobAgentUnsafe" in html
    assert "&lt;script&gt;" in html or "\\u003cscript\\u003e" in html
    decision = {"decision": "Partially Accept", "reason": "Only the cited skill claim is supported.", "evidence_used": "Reviewed job_skills/3."}
    response = client.post(f"/multi-agent/jobs/1/runs/{run['run_id']}/decision", data=decision)
    assert response.status_code == 200
    assert api.call_args.args[1].endswith(f"/jobs/1/runs/{run['run_id']}/decision")
    assert api.call_args.kwargs["json"] == decision
