"""Student 2 Testing Review adapter for saved evidence, never a security waiver."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import time


COLLECTOR_PATH = Path(__file__).resolve().parents[1] / "student-2/testing_review.py"
DESIGN_SOURCES = (
    ".pre-commit-config.yaml", "scripts/security_checks.py", "scripts/security-ruff.toml",
    "student-2/security_checks.py",
    "student-2/ruff.toml", "student-2/SECURITY.md",
)
LIMITATIONS = [
    "A passed check means saved-evidence consistency only, not a current security PASS or release approval.",
    "Recorded input hashes do not cover newly added files; rerun the real hooks for the current commit.",
    "This collector runs no scans, subprocesses, models or application services; human judgment remains pending.",
]


def _load_collector():
    # Only load installed sibling code. The caller's root selects evidence, never code.
    spec = importlib.util.spec_from_file_location("student2_testing_evidence", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("Student 2 evidence collector is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate(snapshot, mode):
    errors = []
    security = snapshot.get("security", {})
    if not isinstance(security, dict):
        return ["Security evidence is missing or malformed."]
    if security.get("gate_status") != "HISTORICAL_RESULTS_ONLY":
        errors.append("Security evidence contains a failed or incomplete gate.")
    scans = security.get("scans", [])
    if not isinstance(scans, list):
        scans = []
    for kind in ("ruff", "secrets", "dependencies"):
        matching = [scan for scan in scans if isinstance(scan, dict) and scan.get("scan") == kind]
        if len(matching) != 1:
            errors.append(f"{kind}: exactly one saved scan is required.")
            continue
        scan = matching[0]
        if scan.get("recorded_status") != "PASS":
            errors.append(f"{kind}: saved scan is failed, missing or incomplete.")
        if scan.get("freshness") != "RECORDED_INPUTS_MATCH":
            errors.append(f"{kind}: recorded inputs are stale or unverified.")
    if mode == "pre_test":
        sources = snapshot.get("design_sources", [])
        if not isinstance(sources, list):
            sources = []
        for name in DESIGN_SOURCES:
            matching = [source for source in sources if isinstance(source, dict) and source.get("file") == name]
            if (len(matching) != 1 or matching[0].get("status") == "MISSING"
                    or not isinstance(matching[0].get("text"), str) or not matching[0]["text"].strip()
                    or not matching[0].get("sha256")):
                errors.append(f"{name}: complete readable design source is required.")
    else:
        ci = snapshot.get("ci", {})
        if not isinstance(ci, dict) or ci.get("status") != "RECORDED_CHECKS_PASS":
            errors.append("CI evidence does not establish the recorded checks passed for the expected commit.")
    return errors


def collect_testing(mode, root, security_dir=None, ci_dir=None, expected_commit=None):
    """Return one full, untruncated saved-evidence check for Student 2 only."""
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    errors, payload, collector = [], {}, None
    if mode not in {"pre_test", "cicd_test"}:
        errors.append("Unsupported Testing Review mode; expected pre_test or cicd_test.")
    else:
        try:
            collector = _load_collector()
            root = Path(root)
            snapshot = collector.collect(mode, root=root, security_dir=security_dir,
                                         ci_dir=ci_dir, expected_commit=expected_commit)
            if not isinstance(snapshot, dict):
                raise ValueError("Invalid evidence snapshot")
            payload.update(snapshot)
            errors.extend(_validate(snapshot, mode))
        except Exception as error:  # An evidence-loading failure must become a visible failed check.
            errors.append(f"Testing evidence could not be collected ({type(error).__name__}).")
            if collector is not None and "security" not in payload:
                try:
                    # Keep known security failures if later design/CI loading failed.
                    payload["security"] = collector.collect_security(
                        Path(root), security_dir or Path(root) / "logs/student-2/security")
                except Exception as recovery_error:
                    errors.append(f"Security evidence recovery failed ({type(recovery_error).__name__}).")
    payload.update(student="student-2", evidence_check_scope="saved-evidence-consistency-only",
                   limitations=list(LIMITATIONS))
    return [{"name": f"testing-{mode}-saved-evidence", "started_at": started_at,
             "finished_at": datetime.now(timezone.utc).isoformat(),
             "duration_seconds": round(time.monotonic() - started, 3),
             "passed": not errors, "validation_errors": errors, "payload": payload}]
