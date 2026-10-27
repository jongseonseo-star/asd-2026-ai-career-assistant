"""Offline report review checks; fixture/model mocks are not submission evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock

import pytest


LOOP_PATH = Path(__file__).resolve().parents[1] / "agentic_loop.py"
TARGET = "a" * 40
REPORT = "Offline fixture only. Dependency scan: FAIL, unresolved FIXTURE-ADVISORY.\nHistorical CI passes do not clear this finding. Current cloud CRUD is UNVERIFIED.\nREPORT-END\n"


@pytest.fixture
def loop():
    spec = importlib.util.spec_from_file_location("tested_report_agentic_loop", LOOP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package(directory, mode="testing_report"):
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "report.txt"
    report.write_text(REPORT, encoding="utf-8")
    raw = directory / "saved-evidence.json"
    raw.write_text('{"fixture_only":true,"status":"FAIL","raw_marker":"RAW-BODY-NOT-SUPPLIED"}')
    manifest = {"mode": mode, "target_commit": TARGET,
        "scope": ["student-2", "student-3", "student-4"],
        "report": {"path": report.name, "sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
        "evidence": [{"label": "Saved fixture result", "path": raw.name,
                      "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}],
        "limitations": ["Fixtures prove no real execution."]}
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def model_transport(monkeypatch, loop, outputs):
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


@pytest.mark.parametrize("mode", ["ma_workflow", "testing_report", "cloud_deployment"])
def test_both_stages_get_identical_intact_report_not_raw_reference_body(loop, tmp_path, monkeypatch, mode):
    path, _ = package(tmp_path, mode)
    implementation_output = " ".join(["fixture"] * 80)
    review_output = " ".join(["fixture"] * 46)
    transport = model_transport(monkeypatch, loop, [implementation_output, review_output])
    evidence = loop.capture_mode(mode, review_manifest=str(path), expected_commit=TARGET)
    assert transport.call_count == 2
    assessments = evidence["agent_assessments"]
    assert assessments["status"] == "completed"
    inputs = [json.loads(assessments[role]["request"]["messages"][1]["content"])
              for role in ("implementation", "review")]
    assert inputs[0]["observed_evidence"] == inputs[1]["observed_evidence"]
    assert inputs[1]["implementation_assessment"] == implementation_output
    assert assessments["implementation"]["word_count"] == 80
    assert assessments["review"]["word_count"] == 46
    observed = inputs[0]["observed_evidence"]["checks"][0]["observed"]
    assert observed["report"]["text"] == REPORT
    assert "FAIL" in observed["report"]["text"] and "UNVERIFIED" in observed["report"]["text"]
    assert observed["report"]["hash_verified"] is True
    assert observed["references"][0]["hash_verified"] is True
    assert observed["references"][0]["content_supplied_to_models"] is False
    assert "RAW-BODY-NOT-SUPPLIED" not in json.dumps(inputs)
    assert observed["expected_commit_matched"] is True
    assert evidence["feature"] == "shared-report"
    assert evidence["review"]["passed"] is True
    assert "not a PASS for source tests" in evidence["review"]["meaning"]
    assert evidence["human_decision"]["status"] == "pending"
    for role in ("implementation", "review"):
        assert assessments[role]["requested_word_limit"] == 80
        assert assessments[role]["context_capacity_check"]["passed"] is True
        assert assessments[role]["request"]["options"]["num_ctx"] == 32768


@pytest.mark.parametrize("fault", ["missing", "hash", "report_hash", "target", "mode", "no_manifest"])
def test_invalid_input_blocks_models_and_keeps_known_report_failures(loop, tmp_path, monkeypatch, fault):
    path, manifest = package(tmp_path)
    if fault == "missing":
        (tmp_path / "saved-evidence.json").unlink()
    elif fault == "hash":
        (tmp_path / "saved-evidence.json").write_text("Changed fixture")
    elif fault == "report_hash":
        manifest["report"]["sha256"] = "0" * 64
    elif fault == "target":
        manifest["target_commit"] = "b" * 40
    elif fault == "mode":
        manifest["mode"] = "ma_workflow"
    path.write_text(json.dumps(manifest))
    transport = Mock(side_effect=AssertionError("Invalid package must not reach a model"))
    monkeypatch.setattr(loop, "urlopen", transport)
    evidence = loop.capture_mode("testing_report", review_manifest=None if fault == "no_manifest" else str(path),
                                 expected_commit=TARGET)
    assert evidence["review"]["passed"] is False
    assert evidence["agent_assessments"]["status"] == "failed"
    assert evidence["checks"][0]["validation_errors"]
    assert evidence["human_decision"]["status"] == "pending"
    if fault != "no_manifest":
        assert evidence["checks"][0]["payload"]["report"]["text"] == REPORT
    transport.assert_not_called()


def test_checks_only_cli_validates_package_without_network_or_execution(tmp_path, monkeypatch, capsys):
    path, _ = package(tmp_path, "cloud_deployment")
    network = Mock(side_effect=AssertionError("Checks-only must not use a model or service"))
    process = Mock(side_effect=AssertionError("Saved reports must not execute commands"))
    monkeypatch.setattr("urllib.request.urlopen", network)
    monkeypatch.setattr("subprocess.run", process)
    monkeypatch.setattr("subprocess.Popen", process)
    output = tmp_path / "check.json"
    monkeypatch.setattr(sys, "argv", [str(LOOP_PATH), "--mode", "cloud_deployment",
        "--review-manifest", str(path), "--expected-commit", TARGET, "--checks-only",
        "--evidence-file", str(output)])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LOOP_PATH), run_name="__main__")
    assert stopped.value.code == 0
    evidence = json.loads(output.read_text())
    assert json.loads(capsys.readouterr().out) == evidence
    assert evidence["agent_assessments"]["status"] == "skipped"
    assert evidence["human_decision"]["status"] == "pending"
    assert "FAIL" in evidence["checks"][0]["payload"]["report"]["text"]
    network.assert_not_called()
    process.assert_not_called()


def test_oversize_report_rejected_intact_before_model_request(loop, tmp_path, monkeypatch):
    path, manifest = package(tmp_path)
    report = tmp_path / "report.txt"
    full_text = "界" * 7000 + "FULL-TAIL"
    report.write_text(full_text)
    manifest["report"]["sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    transport = Mock(side_effect=AssertionError("Oversize input must not reach a model"))
    monkeypatch.setattr(loop, "urlopen", transport)
    evidence = loop.capture_mode("testing_report", review_manifest=str(path), expected_commit=TARGET)
    assert evidence["review"]["passed"] is False
    assert evidence["agent_assessments"]["status"] == "failed"
    assert "20,000-byte" in evidence["agent_assessments"]["error"]
    assert evidence["checks"][0]["payload"]["report"]["text"] == full_text
    assert evidence["agent_assessments"]["observed_evidence"]["checks"][0]["observed"]["report"]["text"] == full_text
    transport.assert_not_called()


@pytest.mark.parametrize("outputs,calls", [([" ".join(["fixture"] * 81)], 1),
                                         (["Fixture assessment.", " ".join(["fixture"] * 81)], 2)])
def test_overlong_assessments_are_saved_as_incomplete(loop, tmp_path, monkeypatch, outputs, calls):
    path, _ = package(tmp_path, "ma_workflow")
    transport = model_transport(monkeypatch, loop, outputs)
    evidence = loop.capture_mode("ma_workflow", review_manifest=str(path), expected_commit=TARGET)
    assert evidence["agent_assessments"]["status"] == "failed"
    role = "implementation" if calls == 1 else "review"
    assert evidence["agent_assessments"][role]["output"] == outputs[-1]
    assert evidence["agent_assessments"][role]["within_requested_word_limit"] is False
    assert evidence["human_decision"]["status"] == "pending"
    assert transport.call_count == calls
    if calls == 1:
        assert "skipped" in evidence["agent_assessments"]["review"]
