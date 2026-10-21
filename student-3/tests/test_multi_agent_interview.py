import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


def load_backend_module():
    backend_file = Path(__file__).resolve().parents[1] / "backend" / "app.py"
    spec = importlib.util.spec_from_file_location("student3_backend_multiagent", backend_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Student-3 backend module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_frontend_module():
    frontend_file = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    spec = importlib.util.spec_from_file_location("student3_frontend_multiagent", frontend_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the Student-3 frontend module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiAgentInterviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend_module()
        self.backend.app.config["TESTING"] = True
        self.client = self.backend.app.test_client()

    def test_multi_agent_question_generation_saves_questions_and_returns_trajectory(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        fake_multi_agent_response = Mock()
        fake_multi_agent_response.status_code = 200
        fake_multi_agent_response.raise_for_status.return_value = None
        fake_multi_agent_response.json.return_value = {
            "status": "completed",
            "release": "Release 2",
            "target_role": "Platform Engineer",
            "iterations": 1,
            "approved": True,
            "plan": {
                "plan_id": "plan-123",
                "competencies": ["Kubernetes", "Observability"],
                "steps": [{"step_id": 1, "title": "Cluster Arch"}],
            },
            "work": {"work_id": "work-123"},
            "review": {"review_id": "rev-123", "verdict": "approved", "score": 90.0, "critique": "Approved."},
            "questions": [
                {"question": "How do you handle zero-downtime cluster upgrades?", "category": "Kubernetes"},
                {"question": "Explain distributed tracing propagation in gRPC.", "category": "Observability"},
            ],
            "trajectory": [
                {"stage": "planning", "agent": "Planner", "action": "Created blueprint"},
                {"stage": "execution", "agent": "Worker", "action": "Generated questions"},
                {"stage": "review", "agent": "Reviewer", "action": "Audited with score 90"},
            ],
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=fake_multi_agent_response) as mocked_post:

            mocked_db.side_effect = [
                ({"id": 10, "target_role": "Platform Engineer", "interview_type": "technical"}, 200),
                ({"id": 101, "session_id": 10, "category": "Kubernetes", "question_text": "Q1"}, 201),
                ({"id": 102, "session_id": 10, "category": "Observability", "question_text": "Q2"}, 201),
            ]

            response = self.client.post(
                "/api/v1/interview-sessions/10/generate-questions",
                json={"mode": "multi-agent", "question_count": 2},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["mode"], "multi-agent")
            self.assertEqual(payload["release"], "Release 2")
            self.assertEqual(len(payload["questions"]), 2)
            self.assertIn("plan", payload)
            self.assertIn("review", payload)
            self.assertIn("trajectory", payload)
            self.assertEqual(payload["review"]["score"], 90.0)

            mocked_post.assert_called_once()
            called_url = mocked_post.call_args[0][0]
            self.assertTrue(called_url.endswith("/interview/prep"))

    def test_multi_agent_evaluate_answer_updates_session_score(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        fake_eval_response = Mock()
        fake_eval_response.status_code = 200
        fake_eval_response.raise_for_status.return_value = None
        fake_eval_response.json.return_value = {
            "status": "completed",
            "release": "Release 2",
            "score": 87.5,
            "feedback": "Strong explanation of stateful sets.",
            "improvement_tips": ["Mention persistent volume claims.", "Discuss backup strategies."],
            "plan": {"dimensions": [{"name": "technical_depth"}]},
            "review": {"verdict": "approved", "score": 92.0, "critique": "Solid technical review."},
            "trajectory": [{"stage": "planning", "agent": "Planner"}, {"stage": "review", "agent": "Reviewer"}],
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=fake_eval_response) as mocked_post:

            mocked_db.side_effect = [
                ({"id": 55, "session_id": 10, "question_text": "Explain StatefulSets vs Deployments."}, 200),
                ({"id": 10, "target_role": "Platform Engineer"}, 200),
                ({"id": 201, "question_id": 55, "score": 87.5}, 201),
                ([{"score": 87.5}], 200),
                ({"id": 10, "overall_score": 87.5}, 200),
            ]

            response = self.client.post(
                "/api/v1/interview-questions/55/evaluate-answer",
                json={"mode": "multi-agent", "answer": "StatefulSets provide stable network identities and persistent storage ordering."},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["mode"], "multi-agent")
            self.assertEqual(payload["release"], "Release 2")
            self.assertEqual(payload["score"], 87.5)
            self.assertIn("improvement_tips", payload)
            self.assertIn("review", payload)

            called_url = mocked_post.call_args[0][0]
            self.assertTrue(called_url.endswith("/interview/evaluate"))

    def test_multi_agent_service_unavailable_raises_dependency_error(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        with patch.object(self.backend, "database_request", return_value=(
            {"id": 10, "target_role": "Platform Engineer"}, 200
        )), patch.object(self.backend.session, "post", side_effect=Exception("Connection refused")):

            response = self.client.post(
                "/api/v1/interview-sessions/10/generate-questions",
                json={"mode": "multi-agent", "question_count": 2},
            )

            self.assertEqual(response.status_code, 503)
            payload = response.get_json()
            self.assertEqual(payload["dependency"], "multi-agent-server")

    def test_dedicated_multi_agent_endpoints(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        fake_resp = Mock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "status": "completed",
            "release": "Release 2",
            "questions": [{"question": "Q1", "category": "Tech"}],
            "plan": {},
            "review": {},
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=fake_resp):

            mocked_db.side_effect = [
                ({"id": 12, "target_role": "Lead Architect"}, 200),
                ({"id": 301, "session_id": 12, "question_text": "Q1"}, 201),
            ]

            response = self.client.post(
                "/api/v1/interview-sessions/12/multi-agent-prep",
                json={"question_count": 1},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["mode"], "multi-agent")

    def test_ai_status_reports_multi_agent_status(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)
        mock_ma_res = Mock()
        mock_ma_res.status_code = 200
        mock_ma_res.json.return_value = {"status": "healthy"}

        with patch.object(self.backend, "get_ollama_models", return_value=["qwen2.5:0.5b"]), \
             patch.object(self.backend.session, "get", return_value=mock_ma_res):

            response = self.client.get("/api/v1/ai/status")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("multi_agent", data["dependencies"])
            self.assertEqual(data["dependencies"]["multi_agent"]["status"], "available")
            self.assertEqual(data["release"], "Release 2")

    def test_frontend_renders_multi_agent_badge_and_options(self):
        frontend = load_frontend_module()
        frontend.app.config["TESTING"] = True
        client = frontend.app.test_client()

        with patch.object(frontend, "backend_request") as mock_backend:
            mock_backend.side_effect = [
                ({"status": "healthy"}, 200),  # health
                ({"status": "ready", "dependencies": {"database": {"status": "healthy"}}}, 200),  # ready
                ({
                    "status": "available",
                    "configured_model": "qwen2.5:0.5b",
                    "configured_model_available": True,
                    "shared_ai_services_enabled": True,
                    "dependencies": {"multi_agent": {"status": "available"}},
                }, 200),  # ai status
                ([], 200),  # sessions
            ]

            response = client.get("/ui/status")
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn("Multi-Agent", text)
            self.assertIn("Connected", text)


if __name__ == "__main__":
    unittest.main()
