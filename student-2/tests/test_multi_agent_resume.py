"""Offline contract tests: every model and HTTP interaction is a fixture."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import requests


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-services"))
from resume_multi_agent import ResumeWorkflowStore, register_resume_routes


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


with patch.dict(os.environ, {"AI_SERVICES_ENABLED": "false", "MULTI_AGENT_ENABLED": "false", "OLLAMA_ENABLED": "false"}):
    backend = load_module("resume_multi_backend", ROOT / "student-2/backend/app.py")
    frontend = load_module("resume_multi_frontend", ROOT / "student-2/frontend/app.py")


CONTEXT = {
    "candidate_profile": {"id": 1, "full_name": "Fixture Candidate", "target_role": "Engineer"},
    "resume": {"id": 2, "candidate_profile_id": 1, "content": "Built a Flask API."},
    "candidate_skills": [{"id": 3, "candidate_profile_id": 1, "skill_name": "Python"}],
}
PLAN = {"objective": "Review supplied resume", "steps": ["Check evidence"], "evidence_ids": ["R1"]}
WORK = {
    "strengths": [{"text": "Built a Flask API.", "evidence_ids": ["R1"]}],
    "skill_gaps": [], "recommended_actions": [], "information_missing": [],
}
REVIEW = {"verdict": "supported", "reason": "The finding matches R1.", "risks": [], "recommendations": []}


def parse(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return None


class SharedResumeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ResumeWorkflowStore(Path(temporary.name))
        self.model = Mock(side_effect=[json.dumps(item) for item in (PLAN, WORK, REVIEW)])
        app = Flask(__name__)
        app.config["TESTING"] = True
        register_resume_routes(app, self.model, parse, {role: f"fixture-{role}" for role in ("Planner", "Worker", "Reviewer")}, self.store)
        self.client = app.test_client()

    def run_workflow(self):
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT, "job_description": "Docker required"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_three_model_stages_preserve_evidence_and_wait_for_actual_human(self):
        record = self.run_workflow()
        self.assertEqual(record["status"], "pending_human_review")
        self.assertEqual(record["human_decision"], {"status": "pending", "decision": None})
        self.assertEqual([item["agent"] for item in record["trajectory"]], ["Planner", "Worker", "Reviewer"])
        self.assertEqual(self.model.call_count, 3)
        for call in self.model.call_args_list:
            self.assertEqual(json.loads(call.args[2])["evidence"]["R1"], CONTEXT["resume"])
        self.assertEqual(self.store.load(record["workflow_id"]), record)
        self.assertEqual(self.client.get(f"/resume/workflows/{record['workflow_id']}").get_json(), record)

    def test_unavailable_model_fails_without_success_fallback_or_human_approval(self):
        self.model.side_effect = [None]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        record = response.get_json()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["human_decision"]["status"], "pending")
        self.assertNotIn("work", record)
        self.model.assert_called_once()
        self.assertEqual(self.store.load(record["workflow_id"])["status"], "failed")

    def test_invalid_model_json_is_retained_as_failure(self):
        self.model.side_effect = ["not JSON"]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["trajectory"][0]["raw_output"], "not JSON")

    def test_unknown_evidence_reference_stops_before_reviewer(self):
        work = copy.deepcopy(WORK)
        work["strengths"][0]["evidence_ids"] = ["INVENTED"]
        self.model.side_effect = [json.dumps(PLAN), json.dumps(work)]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.model.call_count, 2)

    def test_prompts_distinguish_evidence_labels_from_nested_database_ids(self):
        record = self.run_workflow()
        prefix = "Allowed evidence_ids values: "
        for call in self.model.call_args_list:
            prompt = call.args[1]
            allowed_line = next(line for line in prompt.splitlines() if line.startswith(prefix))
            self.assertCountEqual(json.loads(allowed_line[len(prefix):]), record["evidence"])
            self.assertIn("not a nested database id or candidate_profile_id", prompt)
        self.assertIn('"evidence_ids":["R1"]', self.model.call_args_list[0].args[1])
        self.assertIn('"strengths":[{"text":', self.model.call_args_list[1].args[1])

    def test_numeric_database_ids_fail_without_coercion_or_retry(self):
        raw = json.dumps({**PLAN, "evidence_ids": [1, 1, 2, 1]})
        self.model.side_effect = [raw]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        record = response.get_json()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["human_decision"], {"status": "pending", "decision": None})
        self.assertEqual(record["trajectory"][0]["raw_output"], raw)
        self.assertEqual(self.store.load(record["workflow_id"])["trajectory"][0]["raw_output"], raw)
        self.model.assert_called_once()
        self.assertNotIn("work", record)

    def test_prompts_require_evidence_cross_checks_and_distinguish_unknown_skills(self):
        self.run_workflow()
        worker_prompt = self.model.call_args_list[1].args[1]
        reviewer_prompt = self.model.call_args_list[2].args[1]
        self.assertIn("ALL candidate evidence", worker_prompt)
        self.assertIn("not demonstrated in the supplied records", worker_prompt)
        self.assertIn("put an unverified required skill in information_missing", worker_prompt)
        self.assertIn("Independently check EVERY Worker claim against ALL candidate evidence", reviewer_prompt)
        self.assertIn("return verdict needs_correction", reviewer_prompt)
        self.assertIn("Never return an empty reason", reviewer_prompt)

    def test_reviewer_empty_reason_is_retained_as_failure(self):
        raw = json.dumps({**REVIEW, "reason": ""})
        self.model.side_effect = [json.dumps(PLAN), json.dumps(WORK), raw]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        record = response.get_json()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["human_decision"], {"status": "pending", "decision": None})
        self.assertEqual(record["trajectory"][-1]["agent"], "Reviewer")
        self.assertEqual(record["trajectory"][-1]["raw_output"], raw)
        self.assertEqual(self.model.call_count, 3)
        self.assertNotIn("review", record)
        self.assertEqual(self.store.load(record["workflow_id"])["status"], "failed")

    def test_resume_from_another_profile_rejected_before_model(self):
        context = copy.deepcopy(CONTEXT)
        context["resume"]["candidate_profile_id"] = 99
        self.assertEqual(self.client.post("/resume/review", json={"candidate_context": context}).status_code, 400)
        self.model.assert_not_called()

    def test_wrong_json_types_fail_cleanly_without_recording_success(self):
        review = {**REVIEW, "verdict": ["supported"]}
        self.model.side_effect = [json.dumps(item) for item in (PLAN, WORK, review)]
        response = self.client.post("/resume/review", json={"candidate_context": CONTEXT})
        self.assertEqual(response.status_code, 503)
        record = response.get_json()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(self.store.load(record["workflow_id"])["status"], "failed")
        path = f"/resume/workflows/{record['workflow_id']}/human-review"
        response = self.client.post(path, json={"decision": ["accept"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.load(record["workflow_id"])["human_decision"]["status"], "pending")

    def test_human_decision_requires_identity_and_reason_and_cannot_be_overwritten(self):
        record = self.run_workflow()
        path = f"/resume/workflows/{record['workflow_id']}/human-review"
        self.assertEqual(self.client.post(path, json={"decision": "accept"}).status_code, 400)
        result = self.client.post(path, json={"decision": "reject", "reviewer": "Fixture reviewer", "rationale": "Needs more detail."})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["status"], "rejected")
        self.assertEqual(result.get_json()["trajectory"][-1]["agent"], "Human")
        self.assertEqual(self.client.post(path, json={"decision": "accept", "reviewer": "Fixture reviewer", "rationale": "Changed mind"}).status_code, 409)

    def test_correction_requires_text_and_does_not_mutate_evidence(self):
        record = self.run_workflow()
        path = f"/resume/workflows/{record['workflow_id']}/human-review"
        body = {"decision": "correct", "reviewer": "Fixture reviewer", "rationale": "Clarify the recommendation."}
        self.assertEqual(self.client.post(path, json=body).status_code, 400)
        result = self.client.post(path, json={**body, "correction": "Describe verified outcomes only."}).get_json()
        self.assertEqual(result["status"], "correction_recorded")
        self.assertEqual(result["evidence"], record["evidence"])


class ResumeIntegrationTests(unittest.TestCase):
    def setUp(self):
        backend.app.config["TESTING"] = True
        frontend.app.config["TESTING"] = True
        self.client = backend.app.test_client()
        self.addCleanup(patch.stopall)
        self.http = patch.object(requests.Session, "request", side_effect=AssertionError("Unexpected external HTTP")).start()
        patch.object(backend, "AI_SERVICES_ENABLED", True).start()
        patch.object(backend, "MULTI_AGENT_ENABLED", True).start()

    def test_backend_retrieves_real_records_and_forwards_only_canonical_context(self):
        db = patch.object(backend, "database_request", side_effect=[(CONTEXT[key], 200) for key in ("candidate_profile", "resume", "candidate_skills")]).start()
        reply = Mock(status_code=200)
        reply.json.return_value = {"workflow_id": "a" * 32, "status": "pending_human_review"}
        self.http.side_effect = None
        self.http.return_value = reply
        response = self.client.post("/api/v1/ai/multi-agent/resume-review", json={"profile_id": 1, "resume_id": 2, "candidate_context": {"forged": True}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.call_count, 3)
        self.assertEqual(self.http.call_args.kwargs["json"]["candidate_context"], CONTEXT)
        self.assertEqual(self.http.call_args.args[1], backend.MULTI_AGENT_SERVER_URL + "/resume/review")

    def test_cloud_disabled_blocks_model_integration_before_database_or_network(self):
        backend.MULTI_AGENT_ENABLED = False
        with patch.object(backend, "database_request") as db:
            self.assertEqual(self.client.post("/api/v1/ai/multi-agent/resume-review", json={"profile_id": 1, "resume_id": 2}).status_code, 503)
            self.assertEqual(self.client.get("/api/v1/ai/multi-agent/workflows/" + "a" * 32).status_code, 503)
            db.assert_not_called()
            self.http.assert_not_called()

    def test_history_and_human_decision_forward_to_same_shared_server(self):
        reply = Mock(status_code=200)
        reply.json.return_value = {"status": "accepted"}
        self.http.side_effect = None
        self.http.return_value = reply
        body = {"decision": "accept", "reviewer": "Fixture reviewer", "rationale": "Checked against evidence."}
        response = self.client.post("/api/v1/ai/multi-agent/workflows/" + "a" * 32 + "/human-review", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.http.call_args.kwargs["json"]["decision"], "accept")
        self.assertEqual(self.client.get("/api/v1/ai/multi-agent/workflows/not-a-workflow").status_code, 400)

    def test_frontend_proxy_preserves_failed_workflow_and_native_status(self):
        record = {"workflow_id": "a" * 32, "status": "failed", "error": "Planner unavailable"}
        with patch.object(frontend, "backend_request", return_value=(record, 503)):
            response = frontend.app.test_client().post("/ui/multi-agent/run", json={"profile_id": 1, "resume_id": 2})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), record)

    def test_page_contains_review_and_explicit_human_controls(self):
        response = frontend.app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        for text in (b"Multi-Agent Review", b"Record my decision", b"Choose after reviewing the result", b"textContent"):
            self.assertIn(text, response.data)
