"""Offline integration checks; fixture evidence never proves a real scan or model run."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock

import pytest


LOOP_PATH = Path(__file__).resolve().parents[1] / "agentic_loop.py"
DESIGN_FILES = (
    ".pre-commit-config.yaml", "scripts/security_checks.py", "scripts/security-ruff.toml",
    "student-2/security_checks.py",
    "student-2/ruff.toml", "student-2/SECURITY.md",
)


@pytest.fixture
def loop():
    spec = importlib.util.spec_from_file_location("tested_testing_agentic_loop", LOOP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def saved_security(root, *, dependency_failure=False):
    """Only saved, plainly labelled fixture files; no scanner is invoked."""
    hashes = {}
    for name in DESIGN_FILES:
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("Offline fixture design evidence; not executable configuration.\n")
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    directory = root / "logs/student-2/security"
    directory.mkdir(parents=True)
    for kind in ("ruff", "secrets", "dependencies"):
        failed = kind == "dependencies" and dependency_failure
        record = {"scan": kind, "passed": not failed, "exit_code": int(failed),
                  "findings": [], "input_sha256": hashes}
        if kind == "dependencies":
            record["dependencies"] = [{"name": "chromadb", "version": "fixture-version",
                "vulnerabilities": [{"id": "FIXTURE-UNRESOLVED", "fix_versions": []}] if failed else []}]
        (directory / f"{kind}.json").write_text(json.dumps(record))
    return directory


def model_transport(monkeypatch, loop, outputs):
    """Exercise real request construction and response validation, never a model server."""
    responses = []
    for output in outputs:
        response = Mock(status=200)
        response.read.return_value = json.dumps({"done": True, "done_reason": "stop",
                                                "message": {"content": output}}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        responses.append(response)
    transport = Mock(side_effect=responses)
    monkeypatch.setattr(loop, "urlopen", transport)
    return transport


@pytest.mark.parametrize("mode,has_failed_record", [("pre_test", True), ("cicd_test", False)])
def test_checks_only_cli_preserves_failed_or_missing_evidence_without_network(
        tmp_path, monkeypatch, capsys, mode, has_failed_record):
    if has_failed_record:
        saved_security(tmp_path, dependency_failure=True)
    network = Mock(side_effect=AssertionError("Offline CLI must not contact any service"))
    process = Mock(side_effect=AssertionError("Saved evidence must not execute a scanner"))
    monkeypatch.setattr("urllib.request.urlopen", network)
    monkeypatch.setattr("subprocess.run", process)
    monkeypatch.setattr("subprocess.Popen", process)
    output = tmp_path / "execution.json"
    monkeypatch.setattr(sys, "argv", [str(LOOP_PATH), "--mode", mode, "--checks-only",
        "--project-root", str(tmp_path), "--evidence-file", str(output)])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LOOP_PATH), run_name="__main__")
    assert stopped.value.code == 1
    evidence = json.loads(output.read_text())
    assert json.loads(capsys.readouterr().out) == evidence
    assert evidence["mode"] == mode
    assert evidence["review"]["passed"] is False
    assert evidence["agent_assessments"]["status"] == "skipped"
    assert evidence["human_decision"]["status"] == "pending"
    payload = evidence["checks"][0]["payload"]
    assert payload["security"]["gate_status"] == ("FAIL" if has_failed_record else "INCOMPLETE")
    if has_failed_record:
        assert "FIXTURE-UNRESOLVED" in json.dumps(payload)
    else:
        assert payload["ci"]["status"] == "INCOMPLETE"
    network.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize("mode,expected", [
    ("all", ("db", "endpoints", "architecture", "devops", "mcp", "rag")),
    ("release0", ("db", "endpoints", "architecture", "devops")),
])
def test_aggregate_modes_do_not_implicitly_add_testing_reviews(loop, monkeypatch, capsys, mode, expected):
    capture = Mock(return_value={"review": {"passed": True, "checks_passed": True}})
    monkeypatch.setattr(loop, "capture_mode", capture)
    assert loop.run(mode, checks_only=True) == 0
    assert tuple(call.args[0] for call in capture.call_args_list) == expected
    assert tuple(json.loads(capsys.readouterr().out)["mode_results"]) == expected
    assert {"pre_test", "cicd_test"} <= loop.MODES


@pytest.mark.parametrize("mode", ["pre_test", "cicd_test"])
def test_testing_options_reach_collector_without_losing_expected_commit(loop, monkeypatch, tmp_path, mode):
    collector = Mock(return_value=[{"name": "fixture", "passed": False, "payload": {}}])
    monkeypatch.setattr(loop, "collect_testing", collector)
    security, ci = tmp_path / "saved-security", tmp_path / "saved-ci"
    evidence = loop.capture_mode(mode, checks_only=True, project_root=str(tmp_path),
        security_evidence_dir=str(security), ci_evidence_dir=str(ci), expected_commit="fixture-commit")
    collector.assert_called_once_with(mode, tmp_path.resolve(), security_dir=security.resolve(),
                                     ci_dir=ci.resolve(), expected_commit="fixture-commit")
    assert evidence["configuration"]["expected_commit"] == "fixture-commit"
    assert evidence["configuration"]["security_evidence_dir"] == str(security.resolve())


@pytest.mark.parametrize("feature", ["interview", "jobs"])
def test_testing_review_rejects_other_student_features_before_collection(loop, monkeypatch, feature):
    collector = Mock(side_effect=AssertionError("Unsupported feature must not be collected"))
    monkeypatch.setattr(loop, "collect_testing", collector)
    with pytest.raises(ValueError, match="Student 2"):
        loop.capture_mode("pre_test", feature=feature, checks_only=True)
    collector.assert_not_called()


@pytest.mark.parametrize("missing", ["scripts/security_checks.py", "scripts/security-ruff.toml"])
def test_missing_group_scanner_source_blocks_review_without_hiding_failures(loop, tmp_path, missing):
    saved_security(tmp_path, dependency_failure=True)
    (tmp_path / missing).unlink()
    evidence = loop.capture_mode("pre_test", checks_only=True, project_root=str(tmp_path))
    check = evidence["checks"][0]
    assert check["passed"] is False
    assert any(missing in error and "complete readable design source" in error
               for error in check["validation_errors"])
    assert check["payload"]["security"]["gate_status"] == "FAIL"
    assert "FIXTURE-UNRESOLVED" in json.dumps(check["payload"])
    assert evidence["agent_assessments"]["status"] == "skipped"
    assert evidence["human_decision"]["status"] == "pending"


def test_full_testing_source_and_late_finding_survive_evidence_preparation(loop):
    source = "complete source line\n" * 500 + "SOURCE-END"
    finding = {"id": "FIXTURE-LATE-FINDING", "details": "finding details " * 600 + "FINDING-END"}
    payload = {"design_sources": [{"file": "student-2/security_checks.py", "text": source}],
               "security": {"gate_status": "FAIL", "findings": [finding]}}
    observed = loop.assessment_evidence("pre_test", "resume", [
        {"name": "saved evidence", "passed": False, "payload": payload}])
    assert observed["checks"][0]["observed"] == payload
    assert observed["checks"][0]["observed"]["design_sources"][0]["text"].endswith("SOURCE-END")
    assert observed["checks"][0]["observed"]["security"]["findings"][0]["details"].endswith("FINDING-END")
    assert observed["checks_sha256"]


@pytest.mark.parametrize("mode", ["pre_test", "cicd_test"])
def test_oversized_complete_testing_evidence_aborts_before_any_model_request(loop, monkeypatch, mode):
    transport = Mock(side_effect=AssertionError("Over-budget evidence must not reach a model"))
    monkeypatch.setattr(loop, "urlopen", transport)
    source = "x" * 32000 + "FULL-TAIL"
    result = loop.assess_checks(mode, "resume", [
        {"name": "oversized", "passed": False, "payload": {"source": source}}],
        base_url="http://fixture.invalid", timeout=1)
    assert result["status"] == "failed"
    assert "32,000" in result["error"]
    assert result["observed_evidence"]["checks"][0]["observed"]["source"] == source
    transport.assert_not_called()


@pytest.mark.parametrize("mode", ["pre_test", "cicd_test"])
def test_complete_testing_packet_above_old_limit_fits_new_bounded_context(loop, monkeypatch, mode):
    source = "x" * 25000 + "FULL-TAIL"
    transport = model_transport(monkeypatch, loop, ["Fixture assessment.", "Fixture review."])
    result = loop.assess_checks(mode, "resume", [
        {"name": "large fixture", "passed": False, "payload": {"source": source}}],
        base_url="http://fixture.invalid", timeout=1)
    assert result["status"] == "completed"
    assert transport.call_count == 2
    for role, word_limit in (("implementation", 60), ("review", 40)):
        stage = result[role]
        assert stage["request"]["options"]["num_ctx"] == 32768
        assert stage["requested_word_limit"] == word_limit
        capacity = stage["context_capacity_check"]
        assert capacity["passed"] is True
        assert capacity["required_capacity_upper_bound"] == capacity["full_prompt_utf8_bytes"] + 1024
        assert "not a measured token count" in capacity["method"]
        supplied = json.loads(stage["request"]["messages"][1]["content"])
        assert supplied["observed_evidence"]["checks"][0]["observed"]["source"] == source


def test_multibyte_prompt_rejected_by_capacity_before_network_without_truncation(loop, monkeypatch):
    transport = Mock(side_effect=AssertionError("Over-capacity prompt must not reach a model"))
    monkeypatch.setattr(loop, "urlopen", transport)
    source = "界" * 11000 + "FULL-TAIL"
    result = loop.assess_checks("pre_test", "resume", [
        {"name": "multibyte fixture", "passed": False, "payload": {"source": source}}],
        base_url="http://fixture.invalid", timeout=1)
    stage = result["implementation"]
    assert result["status"] == "failed" and stage["completed"] is False
    assert stage["context_capacity_check"]["full_prompt_utf8_bytes"] > 32768
    assert stage["context_capacity_check"]["passed"] is False
    assert "No model request was sent" in stage["error"]
    supplied = json.loads(stage["request"]["messages"][1]["content"])
    assert supplied["observed_evidence"]["checks"][0]["observed"]["source"] == source
    transport.assert_not_called()


def test_capacity_includes_system_prompt_and_reviewer_candidate(loop, monkeypatch):
    transport = Mock(side_effect=AssertionError("Over-capacity prompt must not reach a model"))
    monkeypatch.setattr(loop, "urlopen", transport)
    monkeypatch.setattr(loop, "assessment_prompt", lambda *_: ("s" * 30000, ["offline fixture"]))
    stage = loop.call_assessment("review", "fixture", {"mode": "pre_test"},
        implementation="x" * 4000, base_url="http://fixture.invalid", timeout=1)
    assert stage["completed"] is False
    assert stage["context_capacity_check"]["full_prompt_utf8_bytes"] > 34000
    assert stage["context_capacity_check"]["passed"] is False
    assert "not a measured token count" in stage["context_capacity_check"]["method"]
    transport.assert_not_called()


def test_legacy_context_and_evidence_limit_remain_unchanged(loop, monkeypatch):
    transport = model_transport(monkeypatch, loop, ["Fixture assessment."])
    stage = loop.call_assessment("implementation", "fixture", {"mode": "db"},
        base_url="http://fixture.invalid", timeout=1)
    assert stage["request"]["options"]["num_ctx"] == 8192
    assert "context_capacity_check" not in stage
    transport.reset_mock()
    result = loop.assess_checks("db", "resume", [
        {"name": "legacy fixture", "passed": False, "payload": {"source": "x" * 25000}}],
        base_url="http://fixture.invalid", timeout=1)
    assert result["status"] == "failed" and "24,000" in result["error"]
    transport.assert_not_called()


def test_both_models_get_same_complete_snapshot_and_cannot_waive_dependency_failure(
        loop, monkeypatch, tmp_path):
    saved_security(tmp_path, dependency_failure=True)
    implementation = " ".join(["fixture"] * 60)
    review = " ".join(["fixture"] * 40)
    transport = model_transport(monkeypatch, loop, [implementation, review])
    evidence = loop.capture_mode("pre_test", project_root=str(tmp_path))
    assessments = evidence["agent_assessments"]
    assert assessments["status"] == "completed"
    assert assessments["implementation"]["word_count"] == 60
    assert assessments["review"]["word_count"] == 40
    assert assessments["implementation"]["within_requested_word_limit"] is True
    assert assessments["review"]["within_requested_word_limit"] is True
    messages = [json.loads(call.args[0].data)["messages"] for call in transport.call_args_list]
    first, second = [json.loads(message[1]["content"]) for message in messages]
    assert first["observed_evidence"] == second["observed_evidence"]
    assert "implementation_assessment" not in first
    assert second["implementation_assessment"] == implementation
    assert "FIXTURE-UNRESOLVED" in json.dumps(first["observed_evidence"])
    assert evidence["checks"][0]["payload"]["security"]["gate_status"] == "FAIL"
    assert evidence["review"]["checks_passed"] is False
    assert evidence["review"]["passed"] is False
    assert evidence["human_decision"]["status"] == "pending"
    assert all("student-2/prompts/testing/pre_test_" in path
               for role in ("implementation", "review") for path in assessments[role]["prompt_paths"])


@pytest.mark.parametrize("over_limit_role,outputs,expected_calls", [
    ("implementation", [" ".join(["fixture"] * 61)], 1),
    ("review", ["fixture implementation", " ".join(["fixture"] * 41)], 2),
])
def test_course_word_limits_fail_assessment_without_silent_truncation(
        loop, monkeypatch, over_limit_role, outputs, expected_calls):
    transport = model_transport(monkeypatch, loop, outputs)
    result = loop.assess_checks("cicd_test", "resume", [
        {"name": "fixture", "passed": True, "payload": {"fixture_only": True}}],
        base_url="http://fixture.invalid", timeout=1)
    assert result["status"] == "failed"
    assert result[over_limit_role]["completed"] is False
    assert result[over_limit_role]["output"] == outputs[-1]
    assert result[over_limit_role]["within_requested_word_limit"] is False
    assert "word limit" in result[over_limit_role]["error"]
    assert transport.call_count == expected_calls
    if over_limit_role == "implementation":
        assert result["review"]["completed"] is False
        assert "skipped" in result["review"]


def test_consistent_saved_checks_remain_historical_and_human_pending(loop, tmp_path):
    saved_security(tmp_path)
    evidence = loop.capture_mode("pre_test", project_root=str(tmp_path), checks_only=True)
    assert evidence["review"]["checks_passed"] is True
    assert evidence["checks"][0]["payload"]["security"]["gate_status"] == "HISTORICAL_RESULTS_ONLY"
    assert evidence["checks"][0]["payload"]["evidence_check_scope"] == "saved-evidence-consistency-only"
    assert evidence["human_decision"]["status"] == "pending"
    assert evidence["agent_assessments"]["status"] == "skipped"
