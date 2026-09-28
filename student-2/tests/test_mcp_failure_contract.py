"""Use the real in-process MCP protocol to verify frontend/API failure status."""
import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastmcp import Client as ProtocolClient


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPFailureContractTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        with patch.dict(os.environ, {"AI_SERVICES_ENABLED": "true", "OLLAMA_ENABLED": "false"}):
            self.backend = load_module("s2_mcp_error_backend", ROOT / "student-2/backend/app.py")
            self.server = load_module("s2_mcp_error_server", ROOT / "ai-services/mcp_server.py")
        self.backend.app.config["TESTING"] = True
        self.client = self.backend.app.test_client()
        self.rag = patch.object(self.backend, "request_grounded_feedback", side_effect=AssertionError("MCP failure must not generate feedback")).start()
        patch("fastmcp.Client", side_effect=lambda *_args, **_kwargs: ProtocolClient(self.server.mcp)).start()

    def post(self, **body):
        return self.client.post("/api/v1/ai/resume-feedback", json={"profile_id": 1, "resume_id": 1, **body})

    def test_missing_record_keeps_http_404(self):
        with patch.object(self.server, "database_get", return_value=({"error": "Candidate record was not found."}, 404)):
            response = self.post()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["dependency"], "student-2-database")
        self.rag.assert_not_called()

    def test_foreign_resume_keeps_http_400(self):
        with patch.object(self.server, "database_get", side_effect=[({"id": 1}, 200), ({"id": 1, "candidate_profile_id": 2}, 200)]):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not belong", response.get_json()["error"])
        self.rag.assert_not_called()

    def test_unavailable_database_keeps_http_503(self):
        with patch.object(self.server, "database_get", return_value=({"error": "Candidate database service is unavailable."}, 503)):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["dependency"], "shared-mcp")
        self.rag.assert_not_called()

    def test_invalid_database_record_keeps_http_502(self):
        with patch.object(self.server, "database_get", side_effect=[({"id": 99}, 200), ({"id": 1, "candidate_profile_id": 1}, 200)]):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.rag.assert_not_called()

    def test_sdk_input_failure_keeps_structured_400(self):
        with patch.object(self.server, "database_get", side_effect=AssertionError("Invalid input must not call the DB")):
            result = asyncio.run(self.backend.call_mcp_tool(0, 1))
        self.assertEqual(result["status_code"], 400)
        self.assertTrue(result["error"])

    def test_error_without_structured_contract_is_rejected(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.call_tool.return_value = SimpleNamespace(is_error=True, structured_content=None, content=[])
        with patch("fastmcp.Client", return_value=client):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.rag.assert_not_called()

    def test_success_flag_cannot_hide_error_payload(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.call_tool.return_value = SimpleNamespace(is_error=False, structured_content={"error": "hidden failure", "status_code": 400})
        with patch("fastmcp.Client", return_value=client):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.rag.assert_not_called()


if __name__ == "__main__":
    unittest.main()
