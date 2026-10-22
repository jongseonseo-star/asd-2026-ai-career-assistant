# Student 2 recorded evidence

These ten records preserve historical executions on 22 October 2026. Selecting
them did not run tests, scans, models, GitHub Actions or a deployment.

| Records | Recorded result and limit |
| --- | --- |
| `security-ruff.json`, `security-secrets.json` | PASS for their recorded source scope and revision; not a scan of the final candidate commit. |
| `security-dependencies.json` | Completed audit: ChromaDB 1.5.9, four distinct findings in five entries, exit 1 / FAIL. PYSEC-2026-311 is duplicated. |
| `runtime-junit.xml` | Historical 322-test run, zero failures/errors/skips. This is not the later 325-test terminal result or this commit's CI. |
| `pre-test-live.json`, `pre-test-human-decision.json`, `pre-test-post-review-evidence-check.json` | Recorded model review, separate human partial acceptance, and its after-reference. The unresolved security blocker remains FAIL. |
| `multi-agent-resume-e8238b4a64494961b474cfea0d6e94c6.json` | Three real model stages and the final Human Reject. |
| `multi-agent-terminal-execution.json`, `multi-agent-terminal-human-review.json` | Original terminal/API execution followed by the separate Human Reject submission and read-back. The original pending state is intentionally preserved. |

The later ordinary commit attempt stopped with incomplete dependency audits
(`JSONDecodeError`). That execution error is distinct from the retained completed
audit's vulnerability findings. See [the security status](../../../../student-2/SECURITY.md).

**GitHub CI and CI/CD Review for the candidate commit remain outstanding.**
The resume workflow's Reviewer and Human Review do not establish completion of
the separate development-process Multi-Agent Workflow Review. No record here
approves a merge, deployment or release.

`manifest.json` verifies these ten copies against their preserved originals.
Privacy substitutions replace local paths/hostnames; model outputs, decisions,
rationales and outcomes remain intact. Embedded historical hashes identify the
original bytes; `copy_sha256` identifies a delivered copy. Some referenced raw
HTTP responses and helpers are not bundled, so this is not a complete archive
for recomputing every embedded hash. Excluded records remain available locally.
