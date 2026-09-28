"""Record a person's explicit review in a separate, evidence-bound decision file.

This command never changes automated results or invents a reviewer decision.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def evidence_reference(value):
    if value.startswith(("https://", "http://")):
        return {"url": value, "verification": "Link supplied by reviewer; not fetched by this command."}
    path = Path(value).resolve(strict=True)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"Evidence must be a non-empty file: {path}")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def record_decision(*, evidence_file, output, reviewer, decision, rationale, before, after):
    if decision not in {"accept", "partially-accept", "reject"}:
        raise ValueError("Decision must be accept, partially-accept, or reject.")
    if not reviewer.strip() or not rationale.strip() or not before or not after:
        raise ValueError("Reviewer, rationale and both before/after evidence references are required.")
    evidence_path = Path(evidence_file).resolve(strict=True)
    target = Path(output).resolve()
    if target == evidence_path or target.exists():
        raise ValueError("Use a new decision output file; execution evidence and prior decisions are immutable.")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or not isinstance(evidence.get("review"), dict) or not evidence.get("mode"):
        raise ValueError("Input is not captured agentic-loop evidence.")
    result = {"status": "recorded", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer.strip(), "decision": decision, "rationale": rationale.strip(),
        "reviewed_execution": evidence_reference(str(evidence_path)),
        "before": [evidence_reference(value) for value in before],
        "after": [evidence_reference(value) for value in after],
        "automated_result_unchanged": evidence["review"],
        "meaning": "Explicit reviewer-supplied decision about recommendations; not automatic approval, a signature, or proof of group completion."}
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against overwriting between validation and write.
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", required=True, choices=["accept", "partially-accept", "reject"])
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--before", required=True, action="append", help="Existing file or evidence URL; repeat if needed.")
    parser.add_argument("--after", required=True, action="append", help="Existing retest file or evidence URL; repeat if needed.")
    args = parser.parse_args()
    try:
        print(json.dumps(record_decision(**vars(args)), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Review was not recorded: {error}\n")
