"""Read three Release 2 reports and verify saved references without executing them."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time


REPORT_REVIEW_MODES = ("ma_workflow", "testing_report", "cloud_deployment")
LIMITATIONS = [
    "Only the complete selected report is supplied to the models; referenced files are hash-verified, not supplied as model text.",
    "A valid report package does not turn any recorded FAIL, historical result or unverified claim into a PASS.",
    "This collector runs no application, scan, test, workflow, deployment, subprocess or model.",
    "The models give advice only; a genuine human release decision remains separate and pending.",
]


def _sha(value, length):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{%d}" % length, value) is not None


def _file(reference, directory, errors, label, *, text=False):
    result = {"label": label, "content_supplied_to_models": text, "hash_verified": False}
    if not isinstance(reference, dict):
        errors.append(f"{label}: file reference must be an object.")
        return result
    name, expected = reference.get("path"), reference.get("sha256")
    result.update(path=name, expected_sha256=expected)
    if not isinstance(name, str) or not name.strip() or not _sha(expected, 64):
        errors.append(f"{label}: a non-empty path and full SHA256 are required.")
        return result
    path = Path(name)
    path = (directory / path).resolve() if not path.is_absolute() else path.resolve()
    result["resolved_path"] = str(path)
    try:
        # Streaming the raw references avoids copying large logs into model input or memory.
        digest = hashlib.sha256()
        if text:
            raw = path.read_bytes()
            digest.update(raw)
        else:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
        result["actual_sha256"] = digest.hexdigest()
        result["hash_verified"] = digest.hexdigest() == expected.lower()
        if not result["hash_verified"]:
            errors.append(f"{label}: SHA256 mismatch.")
        if text:
            result["text"] = raw.decode("utf-8")
            if not result["text"].strip():
                errors.append(f"{label}: report must contain non-empty UTF-8 text.")
    except (OSError, UnicodeError) as error:
        errors.append(f"{label}: file is missing or unreadable ({type(error).__name__}).")
    return result


def collect_report_review(mode, manifest_path, expected_commit=None):
    """Return an integrity check, keeping source outcomes distinct from its result.

    Relative file references are resolved against the manifest directory. SHA checks
    establish local file identity, not authenticity or semantic agreement with a report.
    """
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    errors = []
    payload = {"evidence_check_scope": "selected-report-and-reference-integrity-only",
               "limitations": list(LIMITATIONS)}
    try:
        if mode not in REPORT_REVIEW_MODES:
            raise ValueError("Unsupported report review mode.")
        if not manifest_path:
            raise ValueError("--review-manifest is required for report review modes.")
        path = Path(manifest_path).resolve()
        raw = path.read_bytes()
        if len(raw) > 65536:
            raise ValueError("Review manifest exceeds 65,536 bytes; use a smaller selected report package.")
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Review manifest must be a JSON object.")
        payload.update(manifest_path=str(path), manifest_sha256=hashlib.sha256(raw).hexdigest(),
                       mode=manifest.get("mode"), target_commit=manifest.get("target_commit"),
                       scope=manifest.get("scope"), declared_limitations=manifest.get("limitations", []))
        if manifest.get("mode") != mode:
            errors.append("Manifest mode does not match the requested review mode.")
        target = manifest.get("target_commit")
        if not _sha(target, 40):
            errors.append("Manifest target_commit must be a full 40-character commit SHA.")
        if expected_commit is not None:
            if not _sha(expected_commit, 40):
                errors.append("--expected-commit must be a full 40-character commit SHA.")
            elif not isinstance(target, str) or target.lower() != expected_commit.lower():
                errors.append("Manifest target_commit does not match --expected-commit.")
        payload["expected_commit"] = expected_commit
        payload["expected_commit_matched"] = bool(
            _sha(target, 40) and _sha(expected_commit, 40) and target.lower() == expected_commit.lower())
        scope = manifest.get("scope")
        if not isinstance(scope, list) or not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            errors.append("Manifest scope must list the members or features actually covered by this report.")
        limits = manifest.get("limitations", [])
        if not isinstance(limits, list) or not all(isinstance(item, str) for item in limits):
            errors.append("Manifest limitations must be a list of strings when present.")
        payload["report"] = _file(manifest.get("report"), path.parent, errors, "selected report", text=True)
        references = manifest.get("evidence")
        payload["references"] = []
        if not isinstance(references, list) or not references:
            errors.append("Manifest evidence must list at least one actual saved reference.")
        else:
            labels = set()
            for index, reference in enumerate(references):
                label = reference.get("label") if isinstance(reference, dict) else None
                if not isinstance(label, str) or not label.strip():
                    errors.append(f"Evidence reference {index + 1} needs a non-empty label.")
                    label = f"evidence reference {index + 1}"
                if label in labels:
                    errors.append(f"{label}: duplicate evidence label.")
                labels.add(label)
                payload["references"].append(_file(reference, path.parent, errors, label))
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        errors.append(f"Report evidence could not be collected: {type(error).__name__}: {error}")
    return [{"name": f"report-{mode}-saved-evidence", "started_at": started_at,
             "finished_at": datetime.now(timezone.utc).isoformat(),
             "duration_seconds": round(time.monotonic() - started, 3),
             "passed": not errors, "validation_errors": errors, "payload": payload}]
