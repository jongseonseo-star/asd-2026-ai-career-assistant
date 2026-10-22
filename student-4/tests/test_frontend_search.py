import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest


FEATURE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def search_ui(monkeypatch):
    monkeypatch.syspath_prepend(str(FEATURE_DIR / "backend"))

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    backend = load("jobs_search_backend", FEATURE_DIR / "backend/app.py")
    frontend = load("jobs_search_frontend", FEATURE_DIR / "frontend/app.py")
    records = {
        "companies": [{"id": 1, "name": "Example", "industry": "Software", "location": "Sydney", "website": "https://example.test"}],
        "job_postings": [
            {"id": 1, "company_id": 1, "title": "Flask Developer", "location": "Sydney", "description": "Build Python APIs."},
            {"id": 2, "company_id": 1, "title": "Data Analyst", "location": "Melbourne", "description": "Analyse business data."},
        ],
        "job_skills": [{"id": 3, "job_posting_id": 2, "skill_name": "SQL", "importance": "required"}],
    }
    def database_api(method, path, **kwargs):
        return Mock(status_code=200, json=lambda: records[path.rsplit("/", 1)[-1]])

    monkeypatch.setattr(backend, "db_request", database_api)
    backend_client = backend.app.test_client()

    def backend_api(method, path, **kwargs):
        response = backend_client.open(path, method=method, query_string=kwargs.get("params"))
        assert response.status_code == 200
        return Mock(json=response.get_json)

    api = Mock(side_effect=backend_api)
    monkeypatch.setattr(frontend, "api", api)
    return frontend.app.test_client(), api


def test_default_page_shows_all_jobs_and_search_form(search_ui):
    client, api = search_ui
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<form class="form-grid" method="get" action="/">' in page
    assert 'type="search" name="q" value=""' in page
    assert "<h3>Flask Developer</h3>" in page
    assert "<h3>Data Analyst</h3>" in page
    assert '<span>2 records</span>' in page
    api.assert_any_call("GET", "/api/v1/jobs/enriched", params=None)


def test_search_uses_backend_filter_and_preserves_job_options(search_ui):
    client, api = search_ui
    response = client.get("/", query_string={"q": "  Flask  "})
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    api.assert_any_call("GET", "/api/v1/jobs/enriched", params={"q": "Flask"})
    assert 'type="search" name="q" value="Flask"' in page
    assert "<h3>Flask Developer</h3>" in page
    assert "<h3>Data Analyst</h3>" not in page
    assert '<span>1 records</span>' in page
    assert '<option value="2">Data Analyst</option>' in page
    assert '<a href="/">Clear search</a>' in page


def test_unmatched_search_is_escaped_and_has_empty_state(search_ui):
    client, api = search_ui
    query = '<script>alert("search")</script>'
    response = client.get("/", query_string={"q": query})
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    api.assert_any_call("GET", "/api/v1/jobs/enriched", params={"q": query})
    assert "No job postings found." in page
    assert '<span>0 records</span>' in page
    assert "&lt;script&gt;" in page
    assert "<script>alert" not in page
