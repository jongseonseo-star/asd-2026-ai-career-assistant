import json
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ["OLLAMA_ENABLED"] = "false"

AI_SERVICES_DIR = Path(__file__).resolve().parents[1]
if str(AI_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(AI_SERVICES_DIR))

from multi_agent_server import (
    PlannerAgent,
    WorkerAgent,
    ReviewerAgent,
    MultiAgentCoordinator,
    app,
    run_cli_interview_prep,
    run_cli_interview_eval,
)


class MultiAgentServerUnitTests(unittest.TestCase):
    def setUp(self):
        self.planner = PlannerAgent()
        self.worker = WorkerAgent()
        self.reviewer = ReviewerAgent()
        self.coordinator = MultiAgentCoordinator(self.planner, self.worker, self.reviewer)
        self.client = app.test_client()

    def test_planner_creates_structured_prep_plan(self):
        plan = self.planner.plan_interview_prep("Data Engineer", "technical", 3)
        self.assertIn("plan_id", plan)
        self.assertEqual(plan["target_role"], "Data Engineer")
        self.assertIn("steps", plan)
        self.assertGreaterEqual(len(plan["steps"]), 3)
        self.assertIn("rubric", plan)
        self.assertIn("competencies", plan)

    def test_planner_creates_structured_evaluation_plan(self):
        plan = self.planner.plan_answer_evaluation(
            "Backend Engineer",
            "What is ACID?",
            "Atomicity, Consistency, Isolation, Durability.",
        )
        self.assertIn("dimensions", plan)
        self.assertEqual(plan["target_role"], "Backend Engineer")
        self.assertTrue(any(d["name"] == "technical_correctness" for d in plan["dimensions"]))

    def test_worker_synthesizes_questions_aligned_with_plan(self):
        plan = self.planner.plan_interview_prep("Security Architect", "technical", 4)
        work = self.worker.execute_interview_prep(plan, 4)
        self.assertIn("work_id", work)
        self.assertIn("questions", work)
        self.assertEqual(len(work["questions"]), 4)
        for q in work["questions"]:
            self.assertIn("question", q)
            self.assertIn("category", q)
            self.assertIn("key_points", q)

    def test_worker_evaluates_candidate_answer(self):
        plan = self.planner.plan_answer_evaluation(
            "DevOps Engineer",
            "Explain blue-green deployment.",
            "We maintain two identical production environments. Blue is live, green is idle. We deploy to green, test, and cut over router traffic.",
        )
        work = self.worker.execute_answer_evaluation(
            plan,
            "Explain blue-green deployment.",
            "We maintain two identical production environments. Blue is live, green is idle. We deploy to green, test, and cut over router traffic.",
        )
        self.assertIn("score", work)
        self.assertGreater(work["score"], 0)
        self.assertIn("feedback", work)
        self.assertIn("improvement_tips", work)

    def test_reviewer_audits_questions_deliverable(self):
        plan = self.planner.plan_interview_prep("QA Engineer", "technical", 2)
        work = self.worker.execute_interview_prep(plan, 2)
        review = self.reviewer.review_deliverables(plan, work, iteration=1)
        self.assertIn("verdict", review)
        self.assertIn("score", review)
        self.assertIn("critique", review)
        self.assertIn("strengths", review)

    def test_coordinator_orchestrates_interview_prep_workflow(self):
        result = self.coordinator.coordinate_interview_prep(
            target_role="Cloud Architect",
            interview_type="technical",
            question_count=2,
            max_iterations=2,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["release"], "Release 2")
        self.assertEqual(result["target_role"], "Cloud Architect")
        self.assertIn("plan", result)
        self.assertIn("work", result)
        self.assertIn("review", result)
        self.assertEqual(len(result["questions"]), 2)
        self.assertGreaterEqual(len(result["trajectory"]), 3)
        stages = [t["stage"] for t in result["trajectory"]]
        self.assertIn("planning", stages)
        self.assertIn("execution_iteration_1", stages)
        self.assertIn("review_iteration_1", stages)

    def test_coordinator_orchestrates_answer_evaluation_workflow(self):
        result = self.coordinator.coordinate_answer_evaluation(
            target_role="Full Stack Engineer",
            question="How do you handle database migrations safely?",
            candidate_answer="We use expand-and-contract pattern with backwards-compatible schema changes first.",
            max_iterations=2,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["release"], "Release 2")
        self.assertIn("score", result)
        self.assertIn("feedback", result)
        self.assertIn("trajectory", result)

    def test_http_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["release"], "Release 2")
        self.assertIn("planner", payload["agents"])
        self.assertIn("worker", payload["agents"])
        self.assertIn("reviewer", payload["agents"])

    def test_http_list_agents(self):
        response = self.client.get("/agents")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["release"], "Release 2")
        agent_ids = [a["id"] for a in payload["agents"]]
        self.assertEqual(agent_ids, ["planner", "worker", "reviewer"])

    def test_http_interview_prep_endpoint(self):
        response = self.client.post(
            "/interview/prep",
            json={"target_role": "Site Reliability Engineer", "interview_type": "technical", "question_count": 3},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["release"], "Release 2")
        self.assertEqual(len(payload["questions"]), 3)
        self.assertIn("trajectory", payload)

    def test_http_interview_evaluate_endpoint(self):
        response = self.client.post(
            "/interview/evaluate",
            json={
                "target_role": "Python Developer",
                "question": "What is the GIL?",
                "answer": "Global Interpreter Lock ensures only one thread executes Python bytecode at a time in CPython.",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["release"], "Release 2")
        self.assertIn("score", payload)
        self.assertIn("feedback", payload)

    def test_http_interview_evaluate_missing_answer_returns_400(self):
        response = self.client.post(
            "/interview/evaluate",
            json={"target_role": "Python Developer", "question": "What is the GIL?", "answer": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_planner_parses_model_response(self):
        fake_plan = {
            "plan_id": "llm-plan-1",
            "target_role": "Rust Systems Engineer",
            "interview_type": "technical",
            "competencies": ["Memory Safety", "Concurrency", "FFI"],
            "steps": [{"step_id": 1, "title": "Safety", "focus": "Borrow checker", "expected_output": "1 question"}],
            "rubric": {"technical_depth": 0.5, "clarity": 0.5},
        }
        with patch("multi_agent_server.call_ollama", return_value=json.dumps(fake_plan)):
            plan = self.planner.plan_interview_prep("Rust Systems Engineer", "technical", 1)
            self.assertEqual(plan["plan_id"], "llm-plan-1")
            self.assertEqual(plan["target_role"], "Rust Systems Engineer")
            self.assertIn("Planner", plan["generated_by"])

    def test_worker_parses_model_response(self):
        fake_work = {
            "work_id": "llm-work-1",
            "questions": [
                {
                    "question": "How do lifetimes prevent dangling pointers in Rust?",
                    "category": "Memory Safety",
                    "difficulty": "Hard",
                    "key_points": ["Static analysis", "Borrowing"],
                }
            ],
        }
        with patch("multi_agent_server.call_ollama", return_value=json.dumps(fake_work)):
            work = self.worker.execute_interview_prep({}, 1)
            self.assertEqual(work["work_id"], "llm-work-1")
            self.assertEqual(len(work["questions"]), 1)
            self.assertIn("Worker", work["generated_by"])

    def test_reviewer_parses_model_response(self):
        fake_review = {
            "review_id": "llm-review-1",
            "verdict": "approved",
            "score": 94.0,
            "strengths": ["Deep systems focus"],
            "weaknesses": [],
            "critique": "Outstanding technical depth.",
            "revision_recommendations": [],
        }
        with patch("multi_agent_server.call_ollama", return_value=json.dumps(fake_review)):
            review = self.reviewer.review_deliverables({}, {})
            self.assertEqual(review["review_id"], "llm-review-1")
            self.assertEqual(review["verdict"], "approved")
            self.assertEqual(review["score"], 94.0)

    def test_cli_runners_execute_cleanly(self):
        with patch("sys.stdout"):
            run_cli_interview_prep("Platform Engineer", "technical", 2, max_iter=1, as_json=False)
            run_cli_interview_prep("Platform Engineer", "technical", 2, max_iter=1, as_json=True)
            run_cli_interview_eval(
                "Platform Engineer",
                "Explain Kubernetes ingress.",
                "Ingress manages external HTTP/S routing to services.",
                max_iter=1,
                as_json=False,
            )
            run_cli_interview_eval(
                "Platform Engineer",
                "Explain Kubernetes ingress.",
                "Ingress manages external HTTP/S routing to services.",
                max_iter=1,
                as_json=True,
            )


if __name__ == "__main__":
    unittest.main()
