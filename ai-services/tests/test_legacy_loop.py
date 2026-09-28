"""Offline negative cases for real-evidence collectors; fixtures are not run proof."""
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-services"))
import loop_collectors as collectors
from human_review import record_decision


@pytest.fixture
def records():
    return {
        "profiles": [{"id": n, "full_name": f"Fixture {n}", "email": f"fixture{n}@example.test", "target_role": "Engineer", "career_summary": "Fixture summary"} for n in range(1, 11)],
        "resumes": [{"id": n, "candidate_profile_id": n, "title": "Fixture resume", "content": "Fixture skills"} for n in range(1, 11)],
        "skills": [{"id": n, "candidate_profile_id": n, "skill_name": "Python", "proficiency_level": "Intermediate"} for n in range(1, 11)],
    }


def test_database_requires_actual_valid_records_and_ownership(records):
    assert collectors.validate_relations(records) == []
    records["skills"][-1]["candidate_profile_id"] = 999
    assert "orphaned" in " ".join(collectors.validate_relations(records))
    records["profiles"][0]["id"] = True
    assert "positive integers" in " ".join(collectors.validate_relations(records))
    assert collectors.validate_relations({})
    assert collectors.healthy({"status": []})


@pytest.fixture
def ci_fixture(tmp_path, records):
    root = tmp_path / "repo"
    workflow = root / ".github/workflows/student-2.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text((ROOT / ".github/workflows/student-2.yml").read_text())
    reports = root / "reports"
    reports.mkdir()
    report = {"execution_source": "local-ci-equivalent", "job_status": "success", "workflow": "fixture workflow",
        "generated_at_utc": "2026-09-28T00:00:00+00:00", "record_counts": {key: len(value) for key, value in records.items()},
        "ai_services_enabled": False, "ollama_enabled": False, "workflow_sha256": hashlib.sha256(workflow.read_bytes()).hexdigest()}
    (reports / "report.json").write_text(json.dumps(report))
    for resource, data in records.items():
        (reports / f"{resource}.json").write_text(json.dumps(data))
    for name in ("database-health.json", "backend-readiness.json", "frontend-readiness.json"):
        (reports / name).write_text(json.dumps({"status": "healthy"}))
    (reports / "ai-status.json").write_text(json.dumps({"error": "AI generation is disabled in this environment."}))
    for name in ("compose-ps.txt", "compose-logs.txt"):
        (reports / name).write_text("Explicit offline fixture, not actual deployment evidence.")
    return root, reports


def test_local_ci_is_valid_but_never_github_run_proof(ci_fixture):
    result = collectors.collect_devops(*ci_fixture)[0]
    assert result["passed"], result["validation_errors"]
    assert result["payload"]["github_run_proven"] is False


@pytest.mark.parametrize("change", ["missing-artifact", "failed", "stale-workflow", "enabled-ai", "missing-github-run", "wrong-count"])
def test_ci_success_label_cannot_hide_missing_or_inconsistent_evidence(ci_fixture, change):
    root, reports = ci_fixture
    path = reports / "report.json"
    report = json.loads(path.read_text())
    if change == "missing-artifact":
        (reports / "profiles.json").unlink()
    elif change == "failed":
        report["job_status"] = "failure"
    elif change == "stale-workflow":
        report["workflow_sha256"] = "outdated"
    elif change == "enabled-ai":
        report["ollama_enabled"] = True
    elif change == "missing-github-run":
        report["execution_source"] = "github-actions"
    else:
        report["record_counts"]["profiles"] = 11
    path.write_text(json.dumps(report))
    assert collectors.collect_devops(root, reports)[0]["passed"] is False


def test_architecture_requires_live_student2_services_but_not_other_students(tmp_path, monkeypatch):
    for part in ("frontend", "backend", "database"):
        path = tmp_path / "student-2" / part / "app.py"
        path.parent.mkdir(parents=True)
        path.write_text("# offline fixture")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("# offline fixture")
    config = {"services": {name: {"environment": {}} for name in collectors.SERVICES}}
    config["services"]["student-2-frontend"]["environment"] = {"BACKEND_API_URL": "http://student-2-backend:5001"}
    config["services"]["student-2-backend"]["environment"] = {"DATABASE_API_URL": "http://student-2-database:5002",
        "MCP_BASE_URL": "http://host.docker.internal:8765", "RAG_BASE_URL": "http://host.docker.internal:8766", "OLLAMA_BASE_URL": "http://host.docker.internal:11434"}
    config["services"]["student-4-backend"] = {}
    rows = [{"Service": name, "State": "running", "Health": ""} for name in collectors.SERVICES]
    monkeypatch.setattr(collectors, "command", lambda args, root, timeout: json.dumps(config if "config" in args else rows))
    assert collectors.collect_architecture(tmp_path, [compose], "fixture", 2)[0]["passed"] is True
    rows[-1]["State"] = "exited"
    result = collectors.collect_architecture(tmp_path, [compose], "fixture", 2)[0]
    assert result["passed"] is False
    assert "student-2-database" in " ".join(result["validation_errors"])


def test_human_decision_is_explicit_separate_and_cannot_change_automated_failure(tmp_path):
    source = tmp_path / "execution.json"
    source.write_text(json.dumps({"mode": "mcp", "review": {"passed": False}, "human_decision": {"status": "pending"}}))
    original = source.read_bytes()
    output = tmp_path / "decision.json"
    result = record_decision(evidence_file=source, output=output, reviewer="Fixture reviewer", decision="partially-accept",
        rationale="Fixture recommendation needs retest.", before=[str(source)], after=["https://example.test/retest"])
    assert result["automated_result_unchanged"]["passed"] is False
    assert result["reviewed_execution"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() == original
    with pytest.raises(ValueError):
        record_decision(evidence_file=source, output=output, reviewer="Fixture reviewer", decision="accept",
                        rationale="Do not overwrite.", before=[str(source)], after=[str(source)])
    with pytest.raises(ValueError):
        record_decision(evidence_file=source, output=tmp_path / "missing.json", reviewer="", decision="accept",
                        rationale="", before=[], after=[])
