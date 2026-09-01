import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

DATABASE_DIR = Path(__file__).parents[1] / "database"


class DatabaseApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["DB_PATH"] = str(Path(cls.temp.name) / "test.db")
        sys.path.insert(0, str(DATABASE_DIR))
        spec = importlib.util.spec_from_file_location("student4_database_app", DATABASE_DIR / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.client = module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_health_and_seed_minimums(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        counts = self.client.get("/api/v1/stats").get_json()
        self.assertGreaterEqual(counts["companies"], 10)
        self.assertGreaterEqual(counts["job_postings"], 10)
        self.assertGreaterEqual(counts["job_skills"], 10)

    def test_company_crud(self):
        payload = {"name": "Test Company", "industry": "Testing", "location": "Sydney", "website": "https://example.test"}
        created = self.client.post("/api/v1/companies", json=payload)
        self.assertEqual(created.status_code, 201)
        item_id = created.get_json()["id"]
        payload["location"] = "Melbourne"
        self.assertEqual(self.client.put(f"/api/v1/companies/{item_id}", json=payload).get_json()["location"], "Melbourne")
        self.assertEqual(self.client.delete(f"/api/v1/companies/{item_id}").status_code, 204)

    def test_job_and_skill_crud(self):
        job = {
            "company_id": 1, "title": "Test Engineer", "location": "Sydney",
            "employment_type": "Full-time", "experience_level": "Junior",
            "description": "Test APIs and user journeys.", "salary_min": 70000,
            "salary_max": 90000, "closing_date": "2026-10-01", "status": "open",
        }
        created_job = self.client.post("/api/v1/job_postings", json=job)
        self.assertEqual(created_job.status_code, 201)
        job_id = created_job.get_json()["id"]
        skill = {"job_posting_id": job_id, "skill_name": "Pytest", "importance": "required"}
        created_skill = self.client.post("/api/v1/job_skills", json=skill)
        self.assertEqual(created_skill.status_code, 201)
        skill_id = created_skill.get_json()["id"]
        skill["importance"] = "preferred"
        self.assertEqual(self.client.put(f"/api/v1/job_skills/{skill_id}", json=skill).get_json()["importance"], "preferred")
        job["status"] = "closed"
        self.assertEqual(self.client.put(f"/api/v1/job_postings/{job_id}", json=job).get_json()["status"], "closed")
        self.assertEqual(self.client.delete(f"/api/v1/job_postings/{job_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/v1/job_skills/{skill_id}").status_code, 404)

    def test_validation_rejects_bad_salary(self):
        payload = {
            "company_id": 1, "title": "Bad Job", "location": "Sydney",
            "employment_type": "Full-time", "experience_level": "Junior",
            "description": "Invalid salary range.", "salary_min": 100000,
            "salary_max": 50000, "closing_date": "2026-10-01", "status": "open",
        }
        self.assertEqual(self.client.post("/api/v1/job_postings", json=payload).status_code, 400)


if __name__ == "__main__":
    unittest.main()
