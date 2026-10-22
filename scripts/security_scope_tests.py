"""Offline scope/failure checks; these fixtures are not real security evidence."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    spec = importlib.util.spec_from_file_location("security_scope_fixture", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("student", ["student-2", "student-3", "student-4"])
def test_requirements_are_owned_services_and_shared_runtime(student):
    checks = load("student-2/security_checks.py")
    assert checks.requirements_for(student) == tuple(
        f"{student}/{service}/requirements.txt" for service in ("backend", "frontend", "database")
    ) + ("ai-services/requirements.txt",)


@pytest.mark.parametrize("student", ["..", "student-1", "student-2/../student-3", "--all"])
def test_invalid_scope_is_rejected_before_running_tools(student, monkeypatch):
    checks = load("student-2/security_checks.py")
    def forbidden(*args):
        pytest.fail("Invalid scope must not execute a tool")
    monkeypatch.setattr(checks, "run_command", forbidden)
    with pytest.raises(ValueError):
        checks.student_files(student)


def test_git_scope_and_shared_opt_in_are_explicit(tmp_path, monkeypatch):
    checks = load("student-2/security_checks.py")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    paths = ["student-3/app.py", "ai-services/server.py"]
    for name in paths:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture\n")
    commands = []
    def git_files(command):
        commands.append(command)
        selected = paths if "ai-services" in command else paths[:1]
        return SimpleNamespace(returncode=0, stdout="\0".join(selected) + "\0")
    monkeypatch.setattr(checks, "run_command", git_files)
    assert checks.student_files("student-3") == paths[:1]
    assert set(checks.student_files("student-3", include_shared=True)) == set(paths)
    assert commands[0][commands[0].index("--") + 1:] == ["student-3"]
    assert commands[1][commands[1].index("--") + 1:] == ["student-3", "ai-services"]


def test_broken_symlink_in_scan_scope_fails(tmp_path, monkeypatch):
    checks = load("student-2/security_checks.py")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    (tmp_path / "student-2").mkdir()
    (tmp_path / "student-2/link").symlink_to(tmp_path / "absent")
    monkeypatch.setattr(checks, "run_command", lambda command: SimpleNamespace(
        returncode=0, stdout="student-2/link\0"))
    with pytest.raises(RuntimeError):
        checks.student_files()


def test_missing_student_scope_cannot_pass_using_shared_files(tmp_path, monkeypatch):
    checks = load("student-2/security_checks.py")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    (tmp_path / "ai-services").mkdir()
    (tmp_path / "ai-services/server.py").write_text("# fixture\n")
    monkeypatch.setattr(checks, "run_command", lambda command: SimpleNamespace(
        returncode=0, stdout="ai-services/server.py\0"))
    with pytest.raises(RuntimeError):
        checks.student_files("student-4", include_shared=True)


def test_failed_audit_preserves_json_and_raises(tmp_path, monkeypatch):
    checks = load("student-2/security_checks.py")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    paths = ["student-3/app.py", ".pre-commit-config.yaml", "student-2/security_checks.py",
             "scripts/security_checks.py", "scripts/security-ruff.toml", *checks.requirements_for("student-3")]
    for name in paths:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture only\n")
    monkeypatch.setattr(checks, "student_files", lambda *args: ["student-3/app.py"])
    monkeypatch.setattr(checks, "version", lambda name: "fixture-version")
    raw = {"dependencies": [{"name": "fixture-package", "version": "0.0",
                             "vulns": [{"id": "FIXTURE-FAIL", "fix_versions": []}]}]}
    monkeypatch.setattr(checks, "run_command", lambda command: SimpleNamespace(
        returncode=1, stdout=json.dumps(raw)))
    report_dir = tmp_path / "evidence"
    with pytest.raises(AssertionError):
        checks.scan("dependencies", "student-3", report_dir=report_dir)
    report = json.loads((report_dir / "dependencies.json").read_text())
    assert report["passed"] is False
    assert report["exit_code"] == 1
    assert report["student"] == "student-3"
    assert report["dependencies"][0]["vulnerabilities"][0]["id"] == "FIXTURE-FAIL"
    assert "ai-services/requirements.txt" in report["input_sha256"]


def test_group_cli_runs_remaining_members_and_fails_if_any_fail(monkeypatch, capsys, tmp_path):
    cli = load("scripts/security_checks.py")
    calls = []
    def scan(kind, student, shared, directory):
        calls.append((kind, student, shared, directory))
        if student == "student-3":
            raise AssertionError("sensitive diagnostic must not be printed")
    monkeypatch.setattr(cli, "load_checks", lambda: SimpleNamespace(scan=scan))
    assert cli.main(["--scan", "secrets", "--include-shared", "--report-root", str(tmp_path)]) == 1
    assert [x[1] for x in calls] == ["student-2", "student-3", "student-4"]
    assert all(x[2] for x in calls)
    assert calls[2][3] == tmp_path / "student-4/security"
    output = capsys.readouterr().out
    assert "PASS student-4" in output
    assert "sensitive diagnostic" not in output


def test_student2_default_report_directory_remains_compatible(tmp_path, monkeypatch):
    checks = load("student-2/security_checks.py")
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    def missing(*args):
        raise RuntimeError("missing scope")
    monkeypatch.setattr(checks, "student_files", missing)
    monkeypatch.setenv("STUDENT2_SECURITY_REPORT_DIR", str(tmp_path / "legacy-evidence"))
    with pytest.raises(AssertionError):
        checks.scan("ruff")
    report = json.loads((tmp_path / "legacy-evidence/ruff.json").read_text())
    assert report["passed"] is False
    assert report["scope"] == "Student 2 code; dependency audit also includes its shared AI runtime requirements."
