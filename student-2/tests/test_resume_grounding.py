"""Offline regression tests. All model, MCP, and HTTP calls are intercepted."""
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


with patch.dict(os.environ, {"AI_SERVICES_ENABLED": "false", "OLLAMA_ENABLED": "false"}):
    backend = load_module("student2_backend", ROOT / "backend" / "app.py")
    frontend = load_module("student2_frontend", ROOT / "frontend" / "app.py")


CONTEXT = {
    "candidate_profile": {"id": 1, "full_name": "Example Candidate", "target_role": "Backend Engineer", "career_summary": "Built a Python API."},
    "resume": {"id": 2, "candidate_profile_id": 1, "content": "Developed a Flask API with tests."},
    "candidate_skills": [{"id": 3, "candidate_profile_id": 1, "skill_name": "Python", "proficiency_level": "Intermediate", "years_experience": 1}],
}
GUIDANCE = {
    "results": [{"title": "Demonstrate outcomes", "text": "Describe verified outcomes from your work.", "source": "repo://ai-services/knowledge/resume/outcomes.md", "score": 2}],
    "confidence": "medium",
}
FEEDBACK = {
    "Strengths": [{"text": "The resume describes a Flask API with tests.", "citations": ["R1"]}],
    "Skill Gaps": [{"text": "Docker is requested but not demonstrated in the resume.", "citations": ["J1", "R1"]}],
    "Recommended Actions": [{"text": "Add verified outcomes for the API project.", "citations": ["R1", "G1"]}],
    "Information Missing": [{"text": "No deployment outcomes were supplied.", "citations": []}],
}
REQUEST = {"profile_id": 1, "resume_id": 2, "job_description": "Python and Docker experience"}


class ResumeGroundingTests(unittest.TestCase):
    def setUp(self):
        backend.app.config["TESTING"] = True
        self.client = backend.app.test_client()
        self.addCleanup(patch.stopall)
        self.network = patch.object(requests.Session, "request", side_effect=AssertionError("Unexpected external request")).start()
        patch.object(backend, "AI_SERVICES_ENABLED", True).start()
        self.mcp = patch.object(backend, "call_mcp_tool", new_callable=AsyncMock, return_value=copy.deepcopy(CONTEXT)).start()
        self.rag_response = Mock()
        self.answer = {
            "status": "answered", "feedback": "Cited resume feedback", "raw_feedback": json.dumps(FEEDBACK),
            "feedback_sections": copy.deepcopy(FEEDBACK), "confidence": "medium",
            "confidence_basis": "One document matched", "model": "fixture-model",
            "evidence_sources": backend.build_evidence_sources(CONTEXT["candidate_profile"], CONTEXT["resume"], CONTEXT["candidate_skills"], REQUEST["job_description"], GUIDANCE["results"]),
            "retrieval": copy.deepcopy(GUIDANCE), "sources": [GUIDANCE["results"][0]["source"]],
            "generation_metadata": {"called": True, "service": "shared-rag"},
        }
        self.rag_response.json.return_value = self.answer
        self.rag = patch.object(backend.session, "post", return_value=self.rag_response).start()
        self.model = patch.object(backend, "call_ollama", return_value="Strengths\n- Developed a Flask API.").start()
        self.db = patch.object(backend, "database_request", side_effect=AssertionError("Release 1 must retrieve records through MCP")).start()

    def post(self, body=None):
        return self.client.post("/api/v1/ai/resume-feedback", json=REQUEST if body is None else body)

    def test_release1_delegates_generation_to_shared_rag_and_returns_mcp_result(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.mcp.assert_awaited_once_with(1, 2)
        self.db.assert_not_called()
        self.model.assert_not_called()
        self.rag.assert_called_once_with(
            backend.RAG_BASE_URL + "/answer",
            json={"task": "resume-feedback", "feature": "resume", "query": "Backend Engineer Python and Docker experience", "top_k": 3, "candidate_context": CONTEXT, "job_description": REQUEST["job_description"]},
            timeout=backend.RAG_GENERATION_TIMEOUT,
        )
        self.assertEqual(data["feedback_sections"], FEEDBACK)
        self.assertEqual(data["mcp_result"], CONTEXT)
        self.assertEqual(data["mcp_tool"], "resume_context")
        self.assertTrue(data["generation_metadata"]["called"])

    def test_release0_preserves_database_feedback_without_shared_services(self):
        backend.AI_SERVICES_ENABLED = False
        self.db.side_effect = [(CONTEXT["candidate_profile"], 200), (CONTEXT["resume"], 200), (CONTEXT["candidate_skills"], 200)]
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "release0")
        self.model.assert_called_once()
        self.mcp.assert_not_called()
        self.rag.assert_not_called()

    def test_original_ai_mode_remains_selectable_with_shared_services_enabled(self):
        self.db.side_effect = [(CONTEXT["candidate_profile"], 200), (CONTEXT["resume"], 200), (CONTEXT["candidate_skills"], 200)]
        response = self.post({**REQUEST, "mode": "release0"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "release0")
        self.model.assert_called_once()
        self.mcp.assert_not_called()
        self.rag.assert_not_called()

    def test_mcp_mode_returns_records_without_retrieval_or_generation(self):
        response = self.post({**REQUEST, "mode": "mcp"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mcp_result"], CONTEXT)
        self.assertEqual(response.get_json()["status"], "context-only")
        self.assertFalse(response.get_json()["generation_metadata"]["called"])
        self.mcp.assert_awaited_once()
        self.model.assert_not_called()
        self.rag.assert_not_called()

    def test_shared_modes_cannot_bypass_disabled_environment(self):
        backend.AI_SERVICES_ENABLED = False
        self.assertEqual(self.post({**REQUEST, "mode": "mcp-rag"}).status_code, 503)
        self.assertEqual(self.post({**REQUEST, "mode": "mcp"}).status_code, 503)
        self.assertEqual(self.post({**REQUEST, "mode": "other"}).status_code, 400)
        self.mcp.assert_not_called()
        self.model.assert_not_called()
        self.rag.assert_not_called()

    def test_crud_readiness_is_independent_of_shared_ai(self):
        self.db.side_effect = [({"status": "healthy"}, 200), ([CONTEXT["candidate_profile"]], 200)]
        self.assertEqual(self.client.get("/ready").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/profiles").status_code, 200)
        self.mcp.assert_not_called()
        self.model.assert_not_called()

    def test_mcp_transport_errors_are_controlled(self):
        self.mcp.side_effect = ExceptionGroup("transport", [ConnectionError("private detail")])
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private detail", response.get_data(as_text=True))
        self.rag.assert_not_called()

    def test_mcp_missing_and_mismatched_records_keep_client_status(self):
        for status in (400, 404, 502):
            self.mcp.return_value = {"error": "upstream detail", "status_code": status}
            self.assertEqual(self.post().status_code, status)
        self.model.assert_not_called()

    def test_foreign_resume_is_rejected_before_retrieval_or_generation(self):
        self.mcp.return_value["resume"]["candidate_profile_id"] = 99
        self.assertEqual(self.post().status_code, 400)
        self.rag.assert_not_called()

    def test_foreign_skill_data_is_rejected(self):
        self.mcp.return_value["candidate_skills"][0]["candidate_profile_id"] = 99
        self.assertEqual(self.post().status_code, 502)
        self.model.assert_not_called()

    def test_bad_candidate_payload_is_controlled(self):
        for value in (None, {}, {**CONTEXT, "resume": []}):
            self.mcp.return_value = value
            self.assertEqual(self.post().status_code, 502)

    def test_rag_failure_never_silently_falls_back(self):
        self.rag.side_effect = requests.ConnectionError("offline")
        self.assertEqual(self.post().status_code, 503)
        self.model.assert_not_called()

    def test_malformed_rag_answer_is_rejected(self):
        for payload in ([], {}, {**self.answer, "confidence": "certain"}, {**self.answer, "evidence_sources": []}):
            self.rag_response.json.return_value = payload
            self.assertEqual(self.post().status_code, 502)

    def test_no_context_passes_through_without_model_and_query_is_user_controlled(self):
        self.answer.update({"status": "insufficient-context", "feedback": "Insufficient context: no relevant guidance.", "raw_feedback": "", "feedback_sections": {}, "confidence": "low", "sources": [], "retrieval": {"results": []}, "generation_metadata": {"called": False}, "evidence_sources": backend.build_evidence_sources(CONTEXT["candidate_profile"], CONTEXT["resume"], CONTEXT["candidate_skills"], REQUEST["job_description"], [])})
        response = self.post({**REQUEST, "rag_query": "xyzzzyy"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "insufficient-context")
        self.assertEqual(self.rag.call_args.kwargs["json"]["query"], "xyzzzyy")
        self.model.assert_not_called()

    def test_answer_without_retrieval_is_rejected(self):
        self.answer["retrieval"] = {"results": []}
        self.answer["evidence_sources"] = backend.build_evidence_sources(CONTEXT["candidate_profile"], CONTEXT["resume"], CONTEXT["candidate_skills"], REQUEST["job_description"], [])
        self.assertEqual(self.post().status_code, 502)

    def test_unsupported_citations_are_rejected(self):
        for reference in ("invented-source", "J1", "G1"):
            feedback = copy.deepcopy(FEEDBACK)
            feedback["Strengths"][0]["citations"] = [reference]
            self.answer["raw_feedback"] = json.dumps(feedback)
            self.assertEqual(self.post().status_code, 502)

    def test_invalid_ids_description_and_query_do_not_generate(self):
        for body in ({**REQUEST, "profile_id": True}, {**REQUEST, "resume_id": -1}, {**REQUEST, "job_description": []}, {**REQUEST, "rag_query": []}):
            self.assertEqual(self.post(body).status_code, 400)
        self.rag.assert_not_called()
        self.model.assert_not_called()

    def test_disabled_ai_status_does_not_contact_ollama(self):
        self.assertEqual(self.client.get("/api/v1/ai/status").status_code, 503)
        self.network.assert_not_called()


class MCPClientTests(unittest.TestCase):
    def test_mcp_sdk_calls_resume_tool_with_selected_ids(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.call_tool.return_value = SimpleNamespace(structured_content=CONTEXT)
        with patch("fastmcp.Client", return_value=client) as factory:
            result = backend.get_mcp_candidate_context(1, 2)
        factory.assert_called_once_with(backend.MCP_BASE_URL + "/mcp", timeout=backend.SHARED_AI_TIMEOUT)
        client.call_tool.assert_awaited_once_with("resume_context", arguments={"profile_id": 1, "resume_id": 2}, timeout=backend.SHARED_AI_TIMEOUT, raise_on_error=False)
        self.assertEqual(result, CONTEXT)


class OllamaContextTests(unittest.TestCase):
    def test_release0_keeps_runtime_context_default(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"content": "Strengths\n- Uses Python."}}
        with patch.object(backend, "OLLAMA_ENABLED", True), patch.object(backend.session, "post", return_value=response) as post:
            with backend.app.test_request_context():
                backend.call_ollama("system", "candidate")
                self.assertNotIn("configured_num_ctx", backend.g.ollama_metadata)
        self.assertNotIn("num_ctx", post.call_args.kwargs["json"]["options"])
        self.assertNotIn("format", post.call_args.kwargs["json"])
        self.assertEqual(post.call_args.kwargs["json"]["options"]["num_predict"], 512)


class FrontendEvidenceTests(unittest.TestCase):
    def test_mcp_mode_shows_structured_context_without_feedback_cards(self):
        payload = {"feedback": "Current records retrieved. No model was called.", "status": "context-only",
                   "mode": "mcp", "model": "Not called", "mcp_result": CONTEXT, "mcp_tool": "resume_context"}
        with patch.object(frontend, "backend_request", return_value=(payload, 200)) as call:
            response = frontend.app.test_client().post("/ui/ai/resume-feedback", data={**REQUEST, "mode": "mcp"})
        html = response.get_data(as_text=True)
        self.assertEqual(call.call_args.kwargs["json_body"]["mode"], "mcp")
        self.assertIn("Candidate Records", html)
        self.assertIn("candidate_profile", html)
        self.assertNotIn("No structured items", html)
        self.assertNotIn("View raw model response", html)

    def test_sources_feedback_and_identifiers_are_escaped(self):
        frontend.app.config["TESTING"] = True
        malicious = '<script>alert("untrusted")</script>'
        feedback = copy.deepcopy(FEEDBACK)
        feedback["Strengths"][0]["text"] = malicious
        payload = {
            "feedback": "Strengths\n- " + malicious,
            "feedback_sections": feedback,
            "model": "test-model",
            "mode": "mcp-rag",
            "confidence": "low",
            "confidence_basis": "Heuristic retrieval confidence.",
            "evidence_sources": [{"id": "R1", "title": malicious, "kind": "candidate", "source": "javascript:alert(1)", "text": malicious}],
            "context_summary": {"guidance_records": 0},
        }
        with patch.object(frontend, "backend_request", return_value=(payload, 200)):
            response = frontend.app.test_client().post("/ui/ai/resume-feedback", data=REQUEST)
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('href="#evidence-R1"', html)
        self.assertIn("No matching guidance was retrieved", html)
        self.assertIn("Review the claims", html)

    def test_insufficient_context_is_visible_with_mcp_result_and_without_generated_sections(self):
        payload = {"status": "insufficient-context", "feedback": "Insufficient context: no relevant guidance.",
                   "mode": "mcp-rag", "confidence": "low", "confidence_basis": "No retrieved guidance",
                   "context_summary": {"guidance_records": 0}, "mcp_result": CONTEXT, "mcp_tool": "resume_context"}
        with patch.object(frontend, "backend_request", return_value=(payload, 200)) as backend_call:
            response = frontend.app.test_client().post("/ui/ai/resume-feedback", data={**REQUEST, "rag_query": "xyzzzyy"})
        html = response.get_data(as_text=True)
        self.assertIn("Insufficient context", html)
        self.assertIn("The local model was not called", html)
        self.assertIn("View MCP tool result: resume_context", html)
        self.assertNotIn("View raw model response", html)
        self.assertNotIn("No structured items", html)
        self.assertEqual(backend_call.call_args.kwargs["json_body"]["rag_query"], "xyzzzyy")

    def test_dependency_error_is_visible_without_stale_success_result(self):
        with patch.object(frontend, "backend_request", return_value=({"error": "Resume guidance is unavailable."}, 503)):
            response = frontend.app.test_client().post("/ui/ai/resume-feedback", data=REQUEST)
        html = response.get_data(as_text=True)
        self.assertIn("AI feedback failed", html)
        self.assertIn("Resume guidance is unavailable", html)
        self.assertNotIn("Guidance retrieval confidence", html)


if __name__ == "__main__":
    unittest.main()
