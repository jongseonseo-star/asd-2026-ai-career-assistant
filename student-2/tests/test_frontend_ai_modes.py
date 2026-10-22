"""Regression coverage for retaining MCP/RAG controls in Release 2."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "frontend_ai_modes", ROOT / "student-2/frontend/app.py"
)
frontend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = frontend
spec.loader.exec_module(frontend)


class Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "option" and attributes.get("value") in {"release0", "mcp", "mcp-rag"}:
            self.values[attributes["value"]] = attributes


class FrontendAIModesTests(unittest.TestCase):
    def options(self, release):
        collections = [
            [{"id": 1, "full_name": "Demo Candidate", "target_role": "Engineer"}],
            [{"id": 1, "title": "Demo resume", "is_primary": True}],
        ]
        with patch.object(frontend, "backend_request", return_value=({"release": release}, 200)), \
                patch.object(frontend, "fetch_collection", side_effect=collections):
            response = frontend.app.test_client().get("/ui/ai/form")
        self.assertEqual(response.status_code, 200)
        parsed = Options()
        parsed.feed(response.get_data(as_text=True))
        return parsed.values

    def test_release_two_retains_mcp_and_rag_controls(self):
        options = self.options("Release 2")
        self.assertNotIn("disabled", options["mcp"])
        self.assertNotIn("disabled", options["mcp-rag"])
        self.assertIn("selected", options["mcp-rag"])

    def test_release_one_remains_enabled(self):
        options = self.options("Release 1")
        self.assertNotIn("disabled", options["mcp"])
        self.assertNotIn("disabled", options["mcp-rag"])

    def test_release_zero_keeps_shared_modes_disabled(self):
        options = self.options("Release 0")
        self.assertIn("disabled", options["mcp"])
        self.assertIn("disabled", options["mcp-rag"])
        self.assertIn("selected", options["release0"])

    def test_multi_agent_options_stay_disabled_without_release_two(self):
        for release in ("Release 0", "Release 1"):
            with self.subTest(release=release), \
                    patch.object(frontend, "backend_request", return_value=({"release": release}, 200)), \
                    patch.object(frontend, "fetch_collection") as records:
                response = frontend.app.test_client().get("/ui/multi-agent/options")
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.get_json()["enabled"])
                self.assertIn("disabled", response.get_json()["message"])
                records.assert_not_called()

    def test_multi_agent_options_allow_release_two_candidate_selection(self):
        profiles = [{"id": 1, "full_name": "Demo Candidate"}]
        resumes = [{"id": 2, "candidate_profile_id": 1, "title": "Demo resume"}]
        with patch.object(frontend, "backend_request", return_value=({"release": "Release 2"}, 200)), \
                patch.object(frontend, "fetch_collection", side_effect=[profiles, resumes]):
            response = frontend.app.test_client().get("/ui/multi-agent/options")
        self.assertEqual(response.get_json(), {"enabled": True, "profiles": profiles, "resumes": resumes})

    def test_unavailable_backend_does_not_enable_multi_agent(self):
        with patch.object(frontend, "backend_request", side_effect=frontend.BackendUnavailable("Backend unavailable")), \
                patch.object(frontend, "fetch_collection") as records:
            response = frontend.app.test_client().get("/ui/multi-agent/options")
        self.assertEqual(response.status_code, 503)
        records.assert_not_called()
        page = frontend.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('id="multi-agent-controls" disabled', page)


if __name__ == "__main__":
    unittest.main()
