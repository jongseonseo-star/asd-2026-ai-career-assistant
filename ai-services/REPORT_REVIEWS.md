# Release 2 saved report reviews

The shared development loop has three explicit report review modes. They reuse
the implementation-assessment model followed by the independent review model.
They read saved reports; they never run application agents, hooks, tests,
GitHub workflows, deployments, or cloud changes. Existing `all`, `release0`,
`pre_test`, and `cicd_test` behavior remains unchanged.

| Mode | Selected report should state |
| --- | --- |
| `ma_workflow` | Actual application request, Planner/Worker/Reviewer handoffs and outputs, human response, failures, and covered features. Application review is distinct from this development review. |
| `testing_report` | Each covered member's pre-commit security and post-commit CI evidence; dates, revisions, outcomes, unresolved findings, skips and gaps. Deterministic tests remain authoritative. |
| `cloud_deployment` | Target revision, deployment method and workflow conclusion, external access/CRUD evidence, AI-disabled baseline, and unverified or historical coverage. Cloud AI is an optional extension. |

These are review input expectations, not a claim that merely writing a report
fulfils the assessment. Retain actual source evidence and distinguish a historic
execution from current verification. Do not re-label a failed source result when
preparing a report.

## Prepare the input

Create a concise UTF-8 report and a JSON manifest. Include literal excerpts or
objective summaries of essential evidence in the report. Referenced raw file
bodies are **not** supplied to either model; the collector verifies their local
SHA256 only. Hash matching proves local file identity, not authenticity, report
accuracy, a GitHub conclusion, or a current deployment identity.

The manifest contract below uses placeholders that must be replaced with actual
full SHA values. Relative paths use the manifest's directory, not the current
working directory. Absolute paths are also supported.

```json
{
  "mode": "testing_report",
  "target_commit": "ACTUAL_40_HEX_COMMIT_SHA",
  "scope": ["student-2", "student-3", "student-4"],
  "report": {
    "path": "testing-report.md",
    "sha256": "ACTUAL_64_HEX_REPORT_SHA256"
  },
  "evidence": [
    {
      "label": "Actual saved CI result",
      "path": "saved-ci-result.json",
      "sha256": "ACTUAL_64_HEX_FILE_SHA256"
    }
  ],
  "limitations": ["State any unresolved, historical or unverified evidence here."]
}
```

`mode`, `target_commit`, non-empty `scope`, `report`, and at least one labelled
`evidence` reference are required. `limitations` is optional. Use only the scope
actually covered; the collector does not assume all three members are covered.
List the actual relevant source files, not this example file name. Each raw
source may have an older date or revision: preserve that distinction in the
selected report rather than assigning the target revision to old evidence.

Use SHA256 of each file's exact bytes, for example `shasum -a 256 path/to/file`.
Changing a report or raw reference requires updating its recorded hash. The
manifest itself is also hashed in the execution record. The intended review
target and the version of the review tooling can differ; retain both identities
in the submission evidence.

## Validate, then run the models

From the repository root, with the project's Python environment active:

```bash
python ai-services/agentic_loop.py --mode testing_report --review-manifest path/to/manifest.json --expected-commit ACTUAL_40_HEX_COMMIT_SHA --checks-only --evidence-file path/to/testing-input-check.json
IMPLEMENTATION_MODEL=qwen2.5:7b REVIEW_MODEL=llama3.1:8b OLLAMA_BASE_URL=http://127.0.0.1:11434 python ai-services/agentic_loop.py --mode testing_report --review-manifest path/to/manifest.json --expected-commit ACTUAL_40_HEX_COMMIT_SHA --timeout 600 --evidence-file path/to/testing-review.json
```

Use `ma_workflow` and `cloud_deployment` with their own matching manifests and
separate output files. These modes are not implicitly included in `all`.
`--feature` is unused; the manifest scope controls the recorded coverage.
`--evidence-file` is the output, while `--review-manifest` is the saved input.

A missing/unreadable reference, hash mismatch, invalid manifest, or a mismatch
with `--expected-commit` blocks model execution. An omitted `--expected-commit`
is recorded as an unverified comparison; supply the actual SHA for a target
match. Integrity checks do not inspect raw reference contents for agreement
with the report. A source FAIL remains a source FAIL even if the package is
internally consistent and both assessments finish.

The complete selected report plus reference metadata must fit a 20,000-byte
UTF-8 model-input budget. Prefer a report well below that limit, with a concise
reference list. Full logs, package inventories and large source files belong
in referenced evidence; include all material failures and limitations in the
selected report. Oversized input is rejected without silently cutting text.
Both full prompts also pass the existing conservative capacity check for
`num_ctx=32768`, including system instructions and the first model's response.
This is a byte-based upper bound, not an actual tokenizer measurement.

Both report assessments use the existing general prompt's 80-word limit.
They request three short lines of at most 20 words each to keep advice concise;
the recorded/enforced total limit is 80 words. The separate Student 2
`pre_test` and `cicd_test` modes retain their existing 60/40-word limits.
The raw response is retained; overlong, empty or truncated model output is
incomplete, not silently shortened or marked successful. If a model fails,
keep that execution and save a later attempt separately. A mocked test response
or a checks-only run is not a completed model review.

## Human decision and meaning of results

`review.passed` means input integrity and requested model execution completed.
With `--checks-only`, it means input integrity only. Neither result means source
tests/security passed, advice is correct, or a release is approved. Source
outcomes remain in the exact selected report, and `human_decision` stays pending.

A person must read the checks, reports and actual assessments before recording
their real decision. The existing `human_review.py` can bind a separate decision
record to an execution file using its documented `--evidence-file`, `--output`,
`--reviewer`, `--decision` (`accept`, `partially-accept`, `reject`), `--rationale`,
`--before`, and `--after` options. It does not choose the decision or approve a
release automatically. Final release rationale should identify the release
scope, unresolved risks, conditions and any required corrective action. Record
actual after/retest evidence only when that action occurred. Model completion
does not supply a security waiver or the person's release judgment.

Offline validation of this addition:

```bash
python -m pytest ai-services/tests/test_report_reviews.py ai-services/tests/test_testing_loop.py ai-services/tests/test_agentic_loop.py ai-services/tests/test_legacy_loop.py -q
```

These tests use labelled fixtures and mocked transport; they establish neither
a real model execution nor a new application/security/CI/deployment result.
