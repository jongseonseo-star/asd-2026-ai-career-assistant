import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load_backend_module():
    backend_file = Path(__file__).resolve().parents[1] / "backend" / "app.py"
    spec = importlib.util.spec_from_file_location("student3_backend", backend_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Student-3 backend module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module  # type: ignore[return-value]


class InterviewServiceContractTests(unittest.TestCase):
    def test_database_schema_names_are_present(self):
        db_file = Path(__file__).resolve().parents[1] / "database" / "init_db.py"
        text = db_file.read_text(encoding="utf-8")
        self.assertIn("interview_sessions", text)
        self.assertIn("interview_questions", text)
        self.assertIn("interview_responce", text)

    def test_backend_uses_interview_routes(self):
        backend_file = Path(__file__).resolve().parents[1] / "backend" / "app.py"
        text = backend_file.read_text(encoding="utf-8")
        self.assertIn("/api/v1/interview-sessions", text)
        self.assertIn("generate-questions", text)
        self.assertIn("evaluate-answer", text)

    def test_generate_questions_response_includes_questions_list(self):
        backend = load_backend_module()
        app = backend.app
        app.config["TESTING"] = True

        with app.test_client() as client:
            with patch.object(backend, "database_request") as mocked_db, patch.object(
                backend,
                "call_ollama",
                return_value='{"questions": [{"question": "Q1", "category": "API"}, {"question": "Q2", "category": "Security"}]}',
            ):
                mocked_db.side_effect = [
                    ({"id": 1, "target_role": "Python Backend Engineer", "interview_type": "Technical"}, 200),
                    ({"id": 101, "session_id": 1, "category": "API", "question_text": "Q1"}, 201),
                    ({"id": 102, "session_id": 1, "category": "Security", "question_text": "Q2"}, 201),
                ]

                response = client.post(
                    "/api/v1/interview-sessions/1/generate-questions",
                    json={"target_role": "Python Backend Engineer", "interview_type": "Technical", "question_count": 2},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertIn("questions", payload)
                self.assertEqual(len(payload["questions"]), 2)
                self.assertIn("generated_questions", payload)

    def test_shared_context_preserves_structured_mcp_metadata(self):
        backend = load_backend_module()
        setattr(backend, "AI_SERVICES_ENABLED", True)
        rag_response = Mock()
        rag_response.raise_for_status.return_value = None
        rag_response.json.return_value = {
            "results": [{"text": "Use STAR answers.", "source": "repo://interview"}],
            "confidence": "medium",
        }

        with patch.object(backend, "call_mcp_tool", return_value={
            "target_role": "Python Engineer",
            "evaluation_dimensions": ["clarity"],
        }), patch.object(backend.session, "post", return_value=rag_response):
            context = backend.shared_ai_context(
                target_role="Python Engineer",
                interview_type="technical",
                query="Python Engineer technical interview questions",
            )

        self.assertEqual(context["mcp"]["target_role"], "Python Engineer")
        self.assertEqual(context["sources"], ["repo://interview"])

    def test_empty_retrieval_skips_question_generation(self):
        backend = load_backend_module()
        setattr(backend, "AI_SERVICES_ENABLED", True)
        app = backend.app
        app.config["TESTING"] = True

        with app.test_client() as client:
            with patch.object(backend, "database_request", return_value=(
                {"id": 1, "target_role": "Python Backend Engineer", "interview_type": "Technical"}, 200
            )), patch.object(backend, "shared_ai_context", return_value={
                "mcp": {"target_role": "Python Backend Engineer"},
                "retrieved_context": [],
                "sources": [],
                "confidence": "low",
            }), patch.object(backend, "call_ollama") as mocked_ollama:
                response = client.post(
                    "/api/v1/interview-sessions/1/generate-questions",
                    json={"mode": "mcp-rag", "question_count": 2},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "insufficient-context")
        self.assertFalse(payload["generation_metadata"]["called"])
        mocked_ollama.assert_not_called()
        self.assertEqual(payload["mcp_result"]["target_role"], "Python Backend Engineer")

    def test_evaluate_answer_accepts_user_answer_alias(self):
        backend = load_backend_module()
        app = backend.app
        app.config["TESTING"] = True

        with app.test_client() as client:
            with patch.object(backend, "database_request") as mocked_db, patch.object(
                backend,
                "call_ollama",
                return_value='{"score": 85, "feedback": "Strong answer.", "improvement_tips": ["Add examples.", "Mention trade-offs."]}',
            ):
                mocked_db.side_effect = [
                    ({"id": 5, "session_id": 7, "question_text": "How do you keep APIs fast?"}, 200),
                    ({"id": 7, "target_role": "Python Backend Engineer"}, 200),
                    ({"id": 99, "question_id": 5, "user_answer": "I would optimize endpoints."}, 201),
                    ([{"score": 85}], 200),
                    ({"id": 7, "overall_score": 85.0}, 200),
                ]

                response = client.post(
                    "/api/v1/interview-questions/5/evaluate-answer",
                    json={"user_answer": "I would optimize endpoints."},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["score"], 85.0)
                self.assertIn("feedback", payload)

    def test_fetch_mcp_context_error_mapping(self):
        backend = load_backend_module()
        with patch.object(backend, "call_mcp_tool", side_effect=RuntimeError("connection refused")):
            with self.assertRaises(backend.DependencyError) as context:
                backend.fetch_mcp_context("Developer", "technical")
            self.assertEqual(context.exception.dependency, "shared-ai-services")
            self.assertIn("MCP service is unavailable", context.exception.message)

    def test_shared_context_extracts_source_uri_and_filters_blank_chunks(self):
        backend = load_backend_module()
        setattr(backend, "AI_SERVICES_ENABLED", True)
        rag_response = Mock()
        rag_response.raise_for_status.return_value = None
        rag_response.json.return_value = {
            "results": [
                {"text": "   ", "source_uri": "repo://doc1", "chunk_id": "c1"},
                {"text": "Valid interview guidance.", "source_uri": "repo://doc2", "chunk_id": "c2"},
                {"text": "", "chunk_id": "c3"},
            ],
            "confidence": "high",
        }

        with patch.object(backend, "fetch_mcp_context", return_value={"target_role": "Tester"}), \
             patch.object(backend.session, "post", return_value=rag_response):
            context = backend.shared_ai_context(
                target_role="Tester",
                interview_type="technical",
                query="Tester technical interview",
            )

        self.assertEqual(context["retrieved_context"], ["Valid interview guidance."])
        self.assertEqual(context["sources"], ["repo://doc1", "repo://doc2", "c3"])

    def test_bad_model_json_raises_dependency_error_502(self):
        backend = load_backend_module()
        with self.assertRaises(backend.DependencyError) as cm:
            backend.parse_json_text("not json at all")
        self.assertEqual(cm.exception.dependency, "ollama")
        self.assertEqual(cm.exception.status_code, 502)
        self.assertEqual(cm.exception.message, "Model returned invalid JSON.")

        app = backend.app
        app.config["TESTING"] = True
        with app.test_client() as client:
            with patch.object(backend, "database_request", return_value=(
                {"id": 1, "target_role": "Python Backend Engineer", "interview_type": "Technical"}, 200
            )), patch.object(backend, "shared_ai_context", return_value={
                "mcp": {},
                "retrieved_context": ["Grounded text"],
                "sources": ["source1"],
                "confidence": "high",
            }), patch.object(backend, "call_ollama", return_value="Invalid json response"):
                response = client.post(
                    "/api/v1/interview-sessions/1/generate-questions",
                    json={"question_count": 2},
                )
                self.assertEqual(response.status_code, 502)
                data = response.get_json()
                self.assertEqual(data["dependency"], "ollama")
                self.assertEqual(data["error"], "Model returned invalid JSON.")

    def test_ai_status_reports_dependencies_without_503_when_ollama_down(self):
        backend = load_backend_module()
        app = backend.app
        app.config["TESTING"] = True

        with app.test_client() as client:
            with patch.object(backend, "get_ollama_models", side_effect=backend.DependencyError("ollama", "Down")):
                response = client.get("/api/v1/ai/status")
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertIn("dependencies", data)
                self.assertEqual(data["dependencies"]["ollama"]["status"], "unavailable")
                self.assertIn("mcp", data["dependencies"])
                self.assertIn("rag", data["dependencies"])

    def test_service_information_reports_release_1(self):
        backend = load_backend_module()
        app = backend.app
        app.config["TESTING"] = True

        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["release"], "Release 1")

    def test_mcp_inputs_are_capped(self):
        backend = load_backend_module()
        long_role = "R" * 300
        long_type = "T" * 200

        with patch.object(backend, "call_mcp_tool", return_value={"ok": True}) as mock_call:
            backend.fetch_mcp_context(long_role, long_type)
            mock_call.assert_called_once()
            passed_role, passed_type = mock_call.call_args[0]
            self.assertEqual(len(passed_role), 200)
            self.assertEqual(len(passed_type), 80)


if __name__ == "__main__":
    unittest.main()
