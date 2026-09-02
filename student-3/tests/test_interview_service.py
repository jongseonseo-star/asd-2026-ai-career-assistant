import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


def load_backend_module():
    backend_file = Path(__file__).resolve().parents[1] / "backend" / "app.py"
    spec = importlib.util.spec_from_file_location("student3_backend", backend_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    unittest.main()
