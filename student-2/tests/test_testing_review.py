"""Evidence cannot turn missing checks or a security failure into release approval."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SPEC = importlib.util.spec_from_file_location("student2_testing_review", Path(__file__).parents[1] / "testing_review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


@pytest.mark.parametrize("body,status", [
    ('<testsuites><testsuite tests="1"><testcase name="ok"/></testsuite></testsuites>', "PASS"),
    ('<testsuite tests="1" failures="1"><testcase><failure/></testcase></testsuite>', "FAIL"),
    ('<testsuite tests="0" errors="1"/>', "FAIL"),
    ('<testsuites errors="1"><testsuite tests="1"><testcase/></testsuite></testsuites>', "FAIL"),
    ('<testsuite tests="2" skipped="1"><testcase name="ok"/></testsuite>', "INCOMPLETE"),
    ('<testsuite tests="2"><testcase name="ok"/></testsuite>', "INCOMPLETE"),
    ('<testsuite tests="1"><testcase><skipped/></testcase></testsuite>', "INCOMPLETE"),
    ('<testsuite tests="0"/>', "INCOMPLETE"),
    ('<testsuite', "INCOMPLETE"),
    ('<!DOCTYPE testsuite [<!ENTITY x "value">]><testsuite/>', "INCOMPLETE"),
])
def test_junit_does_not_promote_failed_or_incomplete_results(tmp_path, body, status):
    path = tmp_path / "results.xml"
    path.write_text(body)
    assert review.read_junit(path)["status"] == status


def test_missing_junit_is_not_a_pass(tmp_path):
    assert review.read_junit(tmp_path / "missing.xml")["status"] == "INCOMPLETE"


def test_pre_test_keeps_authoritative_group_scanner_sources_complete(tmp_path):
    required = (
        ".pre-commit-config.yaml", "scripts/security_checks.py", "scripts/security-ruff.toml",
        "student-2/security_checks.py", "student-2/ruff.toml", "student-2/SECURITY.md",
    )
    expected = {}
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = f"Offline source fixture for {name}\n" + "complete source evidence\n" * 100 + "SOURCE-END\n"
        path.write_text(text)
        expected[name] = text
    evidence = review.collect("pre_test", root=tmp_path)
    sources = {source["file"]: source for source in evidence["design_sources"]}
    assert set(sources) == set(required)
    for name, text in expected.items():
        assert sources[name]["text"] == text
        assert sources[name]["sha256"] == review.file_hash(tmp_path / name)
    assert evidence["security"]["gate_status"] == "INCOMPLETE"
    assert evidence["human_decision"]["status"] == "pending"


@pytest.mark.parametrize("length,allowed", [(25000, True), (33000, False)])
def test_cli_preserves_full_packet_with_bounded_32000_character_limit(monkeypatch, capsys, length, allowed):
    evidence = {"source": "x" * length + "FULL-TAIL", "human_decision": {"status": "pending"}}
    monkeypatch.setattr(review, "collect", lambda *_args, **_kwargs: evidence)
    monkeypatch.setattr(sys, "argv", ["testing_review.py", "--mode", "pre_test"])
    if allowed:
        review.main()
        assert json.loads(capsys.readouterr().out) == evidence
    else:
        with pytest.raises(SystemExit) as stopped:
            review.main()
        assert stopped.value.code == 2
        captured = capsys.readouterr()
        assert not captured.out and "32,000" in captured.err


def write_scan(directory, kind, *, passed=True, findings=None, hashes=None):
    directory.mkdir(parents=True, exist_ok=True)
    record = {"scan": kind, "passed": passed, "exit_code": 0 if passed else 1,
              "findings": findings or [], "input_sha256": hashes or {}}
    if kind == "dependencies":
        record["dependencies"] = [{"name": "chromadb", "version": "1.5.9", "vulnerabilities": findings or []}]
    (directory / f"{kind}.json").write_text(json.dumps(record))


def test_documentation_change_marks_old_results_stale(tmp_path):
    source = tmp_path / "SECURITY.md"
    source.write_text("before")
    directory = tmp_path / "security"
    write_scan(directory, "ruff", hashes={"SECURITY.md": review.file_hash(source)})
    source.write_text("after")
    scan = review.read_scan(tmp_path, directory, "ruff")
    assert scan["recorded_status"] == "PASS"
    assert scan["freshness"] == "STALE"


def test_nonempty_findings_override_recorded_pass(tmp_path):
    write_scan(tmp_path, "dependencies", findings=[{"id": "PYSEC-2026-311", "fix_versions": []}])
    assert review.read_scan(tmp_path, tmp_path, "dependencies")["recorded_status"] == "FAIL"


def test_corrupt_or_missing_scans_are_incomplete(tmp_path):
    (tmp_path / "ruff.json").write_text("{")
    assert review.collect_security(tmp_path, tmp_path)["gate_status"] == "INCOMPLETE"


@pytest.mark.parametrize("package", [{}, {"name": "example", "version": "1", "vulnerabilities": "invalid"}])
def test_malformed_dependency_inventory_is_incomplete(tmp_path, package):
    record = {"scan": "dependencies", "passed": True, "exit_code": 0, "dependencies": [package]}
    (tmp_path / "dependencies.json").write_text(json.dumps(record))
    assert review.read_scan(tmp_path, tmp_path, "dependencies")["recorded_status"] == "INCOMPLETE"


def ci_fixture(root):
    workflow = root / ".github/workflows/student-2.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("test fixture only")
    directory = root / "ci"
    directory.mkdir()
    (directory / "pytest-results.xml").write_text('<testsuite tests="1"><testcase name="ok"/></testsuite>')
    junit = review.read_junit(directory / "pytest-results.xml")
    report = {"execution_source": "github-actions", "run_url": "https://github.com/example/test/actions/runs/1",
              "run_id": "1", "commit_sha": "fixture-commit", "job_status": "success",
              "run_attempt": "1", "generated_at_utc": "2026-10-19T07:00:00+00:00",
              "workflow_sha256": review.file_hash(workflow), "pytest": {**junit, "step_outcome": "success"}}
    (directory / "report.json").write_text(json.dumps(report))
    write_course_artifacts(directory, report)
    return directory, report


def write_course_artifacts(directory, report):
    summary = report["pytest"]
    markdown = f"""# Student 2 CI Evidence

- Run ID: {report['run_id']}
- Run attempt: {report['run_attempt']}
- Commit SHA: {report['commit_sha']}
- Job status: {report['job_status']}
- Generated at: {report['generated_at_utc']}
- Pytest outcome: {summary['step_outcome']}
- Pytest evidence: {summary['status']}
- Tests: {summary.get('tests', 'not recorded')}
- Failures: {summary.get('failures', 'not recorded')}
- Errors: {summary.get('errors', 'not recorded')}
- Skipped: {summary.get('skipped', 'not recorded')}
"""
    (directory / "test-results.md").write_text(markdown)
    (directory / "test-audit.jsonl").write_text(json.dumps(report) + "\n")


def test_functional_success_does_not_waive_security_failure(tmp_path):
    ci, _ = ci_fixture(tmp_path)
    security = tmp_path / "security"
    for kind in ("ruff", "secrets"):
        write_scan(security, kind)
    write_scan(security, "dependencies", passed=False, findings=[{"id": "PYSEC-2026-311", "fix_versions": []}])
    evidence = review.collect("cicd_test", tmp_path, security, ci, "fixture-commit")
    assert evidence["ci"]["status"] == "RECORDED_CHECKS_PASS"
    assert evidence["security"]["gate_status"] == "FAIL"
    assert evidence["agent_assessments"]["status"] == "not_run"
    assert evidence["human_decision"]["status"] == "pending"
    assert "passed" not in evidence


@pytest.mark.parametrize("change", ["commit", "workflow", "skipped", "summary", "junit"])
def test_ci_requires_matching_evidence_and_successful_execution(tmp_path, change):
    directory, report = ci_fixture(tmp_path)
    if change == "commit":
        report["commit_sha"] = "different-commit"
    elif change == "workflow":
        report["workflow_sha256"] = "different-hash"
    elif change == "skipped":
        report["pytest"]["step_outcome"] = "skipped"
    elif change == "summary":
        report["pytest"]["tests"] = 20
    else:
        (directory / "pytest-results.xml").unlink()
    (directory / "report.json").write_text(json.dumps(report))
    write_course_artifacts(directory, report)
    assert review.collect_ci(tmp_path, directory, "fixture-commit")["status"] == "INCOMPLETE"


@pytest.mark.parametrize("name", ["test-results.md", "test-audit.jsonl"])
@pytest.mark.parametrize("change", ["missing", "empty", "malformed", "stale"])
def test_ci_requires_complete_consistent_course_artifacts(tmp_path, name, change):
    directory, report = ci_fixture(tmp_path)
    path = directory / name
    if change == "missing":
        path.unlink()
    elif change == "empty":
        path.write_text(" \n")
    elif change == "malformed":
        path.write_text("invalid report")
    elif name == "test-results.md":
        path.write_text(path.read_text().replace("fixture-commit", "stale-commit"))
    else:
        path.write_text(json.dumps({**report, "commit_sha": "stale-commit"}) + "\n")
    result = review.collect_ci(tmp_path, directory, "fixture-commit")
    assert result["status"] == "INCOMPLETE"
    assert any(name in issue for issue in result["issues"])


def test_ci_keeps_full_markdown_and_all_audit_records(tmp_path):
    directory, report = ci_fixture(tmp_path)
    markdown = directory / "test-results.md"
    markdown.write_text(markdown.read_text() + "\nReviewer context: " + "evidence " * 1500)
    audit = directory / "test-audit.jsonl"
    old_report = {**report, "run_id": "previous-run"}
    audit.write_text(json.dumps(old_report) + "\n" + json.dumps(report) + "\n")
    result = review.collect_ci(tmp_path, directory, "fixture-commit")
    assert result["status"] == "RECORDED_CHECKS_PASS"
    artifacts = result["course_artifacts"]
    assert artifacts["test-results.md"]["text"] == markdown.read_text()
    assert artifacts["test-results.md"]["sha256"] == review.file_hash(markdown)
    assert artifacts["test-audit.jsonl"]["records"] == [old_report, report]
    assert artifacts["test-audit.jsonl"]["sha256"] == review.file_hash(audit)


@pytest.mark.parametrize("bad_line", ["{", "[]", "{}", ""])
def test_malformed_earlier_audit_record_is_not_hidden(tmp_path, bad_line):
    directory, report = ci_fixture(tmp_path)
    audit = directory / "test-audit.jsonl"
    audit.write_text(bad_line + "\n" + json.dumps(report) + "\n")
    result = review.collect_ci(tmp_path, directory, "fixture-commit")
    assert result["status"] == "INCOMPLETE"
    assert result["course_artifacts"]["test-audit.jsonl"]["text"] == audit.read_text()


def test_duplicate_markdown_status_cannot_hide_a_conflicting_result(tmp_path):
    directory, _ = ci_fixture(tmp_path)
    path = directory / "test-results.md"
    path.write_text(path.read_text() + "\n- Pytest evidence: FAIL\n")
    result = review.collect_ci(tmp_path, directory, "fixture-commit")
    assert result["status"] == "INCOMPLETE"


@pytest.mark.parametrize("failure", ["junit", "report", "audit"])
def test_failed_evidence_remains_failed_with_missing_course_artifact(tmp_path, failure):
    directory, report = ci_fixture(tmp_path)
    (directory / "test-results.md").unlink()
    if failure == "junit":
        (directory / "pytest-results.xml").write_text('<testsuite tests="1" failures="1"><testcase><failure/></testcase></testsuite>')
        (directory / "report.json").unlink()
    elif failure == "report":
        report["job_status"] = "failure"
        (directory / "report.json").write_text(json.dumps(report))
    else:
        report["pytest"]["status"] = "FAIL"
        (directory / "test-audit.jsonl").write_text(json.dumps(report) + "\n")
    result = review.collect_ci(tmp_path, directory, "fixture-commit")
    assert result["status"] == "FAIL"
