"""Lab 11 pre-commit scans; kept outside the existing API test directory."""
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_STUDENTS = ("student-2", "student-3", "student-4")
REQUIREMENTS = (
    "student-2/backend/requirements.txt",
    "student-2/frontend/requirements.txt",
    "student-2/database/requirements.txt",
    "ai-services/requirements.txt",
)


def requirements_for(student):
    if student not in SUPPORTED_STUDENTS:
        raise ValueError("Select a supported student scope.")
    return tuple(f"{student}/{service}/requirements.txt" for service in (
        "backend", "frontend", "database",
    )) + ("ai-services/requirements.txt",)


def run_command(command):
    return subprocess.run(  # noqa: S603 - fixed local tools and repository file paths; no shell.
        command, cwd=ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def student_files(student="student-2", include_shared=False):
    requirements_for(student)  # Validate before passing any scope to Git or tools.
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required to determine the scan scope.")
    result = run_command([
        git, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
        student, *(["ai-services"] if include_shared else []),
    ])
    if result.returncode:
        raise RuntimeError("Could not determine the selected file list.")
    paths = sorted(set(filter(None, result.stdout.split("\0"))))
    if any((ROOT / name).is_symlink() for name in paths):
        raise RuntimeError("Scan scope contains a symbolic link.")
    files = [name for name in paths if (ROOT / name).is_file()]
    if not files or not any(name.startswith(student + "/") for name in files):
        raise RuntimeError("Selected student scan scope is empty.")
    return files


def scan(kind, student="student-2", include_shared=False, report_dir=None):
    requirements = requirements_for(student)
    scope = ("Student 2 code; dependency audit also includes its shared AI runtime requirements."
             if student == "student-2" and not include_shared else
             f"{student} code" + (" and shared ai-services code" if include_shared else "")
             + "; dependency audit also includes the shared AI runtime requirements.")
    report = {
        "scan": kind,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "passed": False,
        "scope": scope,
        "student": student,
        "shared_source_included": include_shared,
    }
    try:
        files = student_files(student, include_shared)
        ruff_config = ("student-2/ruff.toml" if student == "student-2" and not include_shared
                       else "scripts/security-ruff.toml")
        inputs = sorted(set(files + list(requirements) + [
            ".pre-commit-config.yaml", "student-2/security_checks.py", ruff_config,
            "scripts/security_checks.py",
        ]))
        report["input_sha256"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs
        }
        if kind == "ruff":
            report["tool_version"] = version("ruff")
            result = run_command([
                sys.executable, "-m", "ruff", "check", "--no-cache",
                "--config", ruff_config, "--output-format", "json", student,
                *(["ai-services"] if include_shared else []),
            ])
            findings = json.loads(result.stdout)
            if not isinstance(findings, list):
                raise ValueError("Unexpected Ruff result format.")
            report["findings"] = [
                {"file": str(Path(item["filename"]).relative_to(ROOT)),
                 "line": item["location"]["row"], "rule": item["code"]}
                for item in findings
            ]
            report["passed"] = result.returncode == 0 and not findings
        elif kind == "secrets":
            report["tool_version"] = version("detect-secrets")
            result = run_command([
                sys.executable, "-m", "detect_secrets", "scan", "--no-verify", *files,
            ])
            findings = json.loads(result.stdout)["results"]
            if not isinstance(findings, dict):
                raise ValueError("Unexpected detect-secrets result format.")
            # Retain locations and detector names, never secret values or source lines.
            report["findings"] = [
                {"file": name, "line": item["line_number"], "type": item["type"]}
                for name, items in findings.items() for item in items
            ]
            report["passed"] = result.returncode == 0 and not findings
        elif kind == "dependencies":
            report["tool_version"] = version("pip-audit")
            command = [sys.executable, "-m", "pip_audit"]
            for name in requirements:
                command.extend(["-r", name])
            command.extend([
                "--strict", "--format", "json", "--progress-spinner", "off",
                "--cache-dir", str(Path(tempfile.gettempdir()) / "asd-student2-audit-cache"),
            ])
            result = run_command(command)
            dependencies = json.loads(result.stdout)["dependencies"]
            if not isinstance(dependencies, list) or not dependencies:
                raise ValueError("Dependency audit returned no package evidence.")
            report["requirements"] = list(requirements)
            report["dependencies"] = [
                {"name": item["name"], "version": item.get("version"),
                 "skip_reason": item.get("skip_reason"),
                 "vulnerabilities": [
                     {"id": finding["id"], "fix_versions": finding.get("fix_versions", [])}
                     for finding in item.get("vulns", [])
                 ]}
                for item in dependencies
            ]
            report["passed"] = result.returncode == 0 and all(
                not item.get("vulns") and not item.get("skip_reason") for item in dependencies
            )
        else:
            raise ValueError("Unknown security scan.")
        report["exit_code"] = result.returncode
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Tool output and exception messages can contain source text or credentials.
        report["error"] = f"{type(error).__name__}: scan could not complete; investigate locally."
    report_dir = Path(report_dir or os.getenv(
        student.upper().replace("-", "") + "_SECURITY_REPORT_DIR",
        str(ROOT / "logs" / student / "security"),
    ))
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{kind}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        # An explicit exception also blocks the CLI under Python optimization (-O).
        raise AssertionError(f"{kind} scan failed. See the redacted evidence in {path}.")
    return report


def test_ruff_scan():
    scan("ruff")


def test_secrets_scan():
    scan("secrets")


def test_dependency_audit():
    scan("dependencies")
