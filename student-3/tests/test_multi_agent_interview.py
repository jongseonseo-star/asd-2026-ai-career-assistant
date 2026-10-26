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

    def test_fifteen_iterations_returns_pending_human_review_without_saving(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        fake_resp = Mock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "status": "pending_human_review",
            "run_id": "run-loop15-test",
            "iterations": 15,
            "approved": False,
            "human_decision": {"status": "pending"},
            "questions": [
                {"question": "Proposed question 1", "category": "Tech"},
                {"question": "Proposed question 2", "category": "Tech"},
            ],
            "review": {"score": 68.0, "verdict": "needs_revision", "critique": "Needs higher depth after 15 loops."},
            "plan": {"competencies": ["Tech"]},
            "trajectory": [],
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=fake_resp) as mocked_post:

            mocked_db.side_effect = [
                ({"id": 10, "target_role": "Architect", "interview_type": "technical"}, 200),
            ]

            response = self.client.post(
                "/api/v1/interview-sessions/10/generate-questions",
                json={"mode": "multi-agent-loop15", "question_count": 2},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "pending_human_review")
            self.assertFalse(payload["approved"])
            self.assertEqual(payload["iterations"], 15)
            self.assertEqual(len(payload["questions"]), 2)
            # Questions are proposed, not saved to DB yet
            self.assertTrue(str(payload["questions"][0]["id"]).startswith("proposed-"))
            self.assertEqual(mocked_db.call_count, 1)  # Only GET session, no POST question

            post_kwargs = mocked_post.call_args[1]["json"]
            self.assertEqual(post_kwargs["force_iterations"], 15)

    def test_session_human_review_accept_persists_questions(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        mock_ma_resp = Mock()
        mock_ma_resp.status_code = 200
        mock_ma_resp.json.return_value = {
            "status": "completed",
            "human_decision": {"decision": "Accept", "reviewer": "User"},
            "trajectory": [{"stage": "human_review", "agent": "Human"}],
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=mock_ma_resp):

            mocked_db.side_effect = [
                ({"id": 10, "interview_type": "technical"}, 200),  # GET session
                ({"id": 501, "session_id": 10, "question_text": "Q1"}, 201),  # POST q1
                ({"id": 502, "session_id": 10, "question_text": "Q2"}, 201),  # POST q2
            ]

            response = self.client.post(
                "/api/v1/interview-sessions/10/human-review",
                json={
                    "run_id": "run-loop15-test",
                    "decision": "Accept",
                    "reviewer": "Interviewer Bob",
                    "rationale": "Good technical depth.",
                    "questions": [
                        {"question_text": "Q1", "category": "Tech"},
                        {"question_text": "Q2", "category": "Tech"},
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "completed")
            self.assertTrue(payload["approved"])
            self.assertEqual(payload["decision"], "Accept")
            self.assertEqual(len(payload["questions"]), 2)
            self.assertEqual(mocked_db.call_count, 3)

    def test_question_human_review_accept_saves_response_and_updates_session(self):
        setattr(self.backend, "AI_SERVICES_ENABLED", True)

        mock_ma_resp = Mock()
        mock_ma_resp.status_code = 200
        mock_ma_resp.json.return_value = {
            "status": "completed",
            "human_decision": {"decision": "Accept", "reviewer": "User"},
        }

        with patch.object(self.backend, "database_request") as mocked_db, \
             patch.object(self.backend.session, "post", return_value=mock_ma_resp):

            mocked_db.side_effect = [
                ({"id": 55, "session_id": 10, "question_text": "Describe Paxos."}, 200),  # GET question
                ({"id": 888, "question_id": 55, "score": 88.0}, 201),  # POST response
                ([{"score": 88.0}], 200),  # GET responses
                ({"id": 10, "overall_score": 88.0}, 200),  # PUT session
            ]

            response = self.client.post(
                "/api/v1/interview-questions/55/human-review",
                json={
                    "run_id": "run-eval-test",
                    "decision": "Accept",
                    "reviewer": "Senior Lead",
                    "rationale": "Clear consensus explanation.",
                    "candidate_answer": "Paxos reaches consensus through prepare and accept phases.",
                    "feedback": "Strong foundational understanding.",
                    "improvement_tips": "Mention Raft comparisons.",
                    "score": 88.0,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "completed")
            self.assertTrue(payload["approved"])
            self.assertEqual(payload["score"], 88.0)

    def test_frontend_renders_human_review_ui_and_handles_submission(self):
        frontend = load_frontend_module()
        frontend.app.config["TESTING"] = True
        client = frontend.app.test_client()

        with patch.object(frontend, "backend_request") as mock_backend:
            # 1. When questions require human review
            mock_backend.return_value = ({
                "status": "pending_human_review",
                "run_id": "run-12345",
                "iterations": 15,
                "approved": False,
                "review": {"score": 72.0, "verdict": "needs_revision", "critique": "Not detailed enough."},
                "generated_questions": [
                    {"id": "proposed-1", "question_text": "Explain CAP theorem.", "category": "Systems"}
                ],
            }, 200)

            resp = client.post("/ui/questions/generate", data={"session_id": "10", "mode": "multi-agent-loop15"})
            self.assertEqual(resp.status_code, 200)
            text = resp.get_data(as_text=True)
            self.assertIn("Human Review Required", text)
            self.assertIn("15 Iterations Complete", text)
            self.assertIn("/ui/sessions/10/human-review", text)
            self.assertIn("Explain CAP theorem.", text)

            # 2. When human review is confirmed
            mock_backend.return_value = ({
                "status": "completed",
                "approved": True,
                "decision": "Accept",
                "questions": [
                    {"id": 101, "question_text": "Explain CAP theorem.", "category": "Systems"}
                ],
            }, 200)

            resp_review = client.post(
                "/ui/sessions/10/human-review",
                data={
                    "decision": "Accept",
                    "reviewer": "Reviewer Alice",
                    "rationale": "Approved manually.",
                    "run_id": "run-12345",
                    "questions_json": '[{"id": 101, "question_text": "Explain CAP theorem."}]',
                },
            )
            self.assertEqual(resp_review.status_code, 200)
            text_review = resp_review.get_data(as_text=True)
            self.assertIn("Human Review Completed (Accept)", text_review)
            self.assertIn("Reviewer Alice", text_review)
            self.assertIn("Q1.", text_review)


if __name__ == "__main__":
    unittest.main()
