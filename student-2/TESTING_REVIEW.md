# Student 2 testing review

This prepares inputs for the existing shared Agentic Loop using the
[Lab 11 review pattern](https://github.com/Georges034302/asd-labs/blob/main/Lab_11_Testing_Deployment_and_Operations.md#7-agentic-loop-integration).
`testing_review.py` collects local evidence and writes a snapshot. It does not
call a model, start a service, change the application, approve findings, or
implement a separate Agentic Loop. The existing shared loop now provides
explicit `pre_test` and `cicd_test` modes through `ai-services/loop_testing.py`.

## Collect an evidence snapshot

Run from the repository root using the existing Python environment. Replace
the paths with the actual saved scan reports or downloaded CI artifact:

```bash
python student-2/testing_review.py --mode pre_test \
  --security-dir logs/student-2/security \
  --output logs/student-2/testing/pre-test-evidence.json

python student-2/testing_review.py --mode cicd_test \
  --security-dir logs/student-2/security \
  --ci-dir reports/student-2 \
  --output logs/student-2/testing/ci-test-evidence.json
```

Add `--expected-commit FULL_COMMIT_SHA` when comparing CI evidence with a
specific committed revision. Use an actual SHA; omitting it does not establish
that evidence belongs to the intended revision. `--output PATH` selects the
snapshot destination. These commands collect evidence; they do not rerun scans
or tests. Retain the original source reports alongside the snapshot.

The pre-test snapshot should identify the actual hook/test implementation,
the three scan reports, known findings, and missing or stale inputs. Editing
Student 2 documentation or code can invalidate existing scan-input hashes.
The CI snapshot should distinguish pytest outcome/JUnit evidence, workflow
status at capture time, run/commit identity, and missing evidence. A saved
status before teardown or artifact upload is not the final run conclusion.

At preparation time, the known dependency audit is failing and the changed
workflow has no demonstrated GitHub Actions run. Old 209-test local success is
historical evidence. Do not invent a run URL, record unexecuted work as PASS,
or replace the raw failure with a review recommendation. See
[SECURITY.md](SECURITY.md) for the Chroma assessment and its limits.

## Use the existing shared loop

The four files under `prompts/testing/` provide implementation and review
prompts for `pre_test` and `cicd_test`. Their output limits follow Lab 11:
60 words for the initial assessment and 40 words for the review.

Both modes pass the complete evidence snapshot to the implementation model
and then to the review model together with the implementation output. Testing
responses exceeding 60/40 words fail instead of silently counting as completed.
Testing evidence exceeding 32,000 characters is rejected before any model call;
the snapshot CLI uses the same 32,000-character cap. Findings and full source
text are not truncated. The pre-test sources include the group hook, dispatcher,
shared Ruff policy, Student 2 scanner and Ruff policy, and security documentation.

Both testing modes request `num_ctx=32768`. Before each request, the complete
system and user prompt content is measured in UTF-8 bytes, including the actual
implementation assessment in the review request. The byte total plus a 1,024
output/template reserve must not exceed 32,768. This is a conservative capacity
check for the configured Qwen/Llama byte-level tokenizers, not a measured token
count. The reserve covers the unchanged 512-token output budget and template
overhead; the assessment word limits remain 60/40. A failed capacity check
records its byte counts, sends no request, and preserves the complete evidence.

Existing non-testing modes retain the 24,000-character evidence cap and
`num_ctx=8192`. Existing `all` and `release0` mode selections are unchanged;
select a testing mode explicitly. These capacity checks establish neither
model quality nor a fresh security-scan result.

For a local connection check that does not call models, services or scanners:

```bash
python ai-services/agentic_loop.py --mode pre_test --checks-only \
  --security-evidence-dir logs/student-2/security \
  --evidence-file logs/student-2/testing/pre-test-connection.json

python ai-services/agentic_loop.py --mode cicd_test --checks-only \
  --security-evidence-dir logs/student-2/security \
  --ci-evidence-dir reports/student-2 --expected-commit FULL_COMMIT_SHA \
  --evidence-file logs/student-2/testing/ci-test-connection.json
```

Use an actual committed SHA for the second command. Missing, failed or stale
evidence produces exit code 1 and retains its explanation in the output.
This can demonstrate a working failure path; it is not a failed installation.
CI review also reads `test-results.md` and `test-audit.jsonl`, preserving their
content and checking consistency with `report.json` and the JUnit artifact.

For a later real assessment, remove `--checks-only` and configure the existing
`IMPLEMENTATION_MODEL`, `REVIEW_MODEL` and `OLLAMA_BASE_URL` environment variables.
That calls the configured model server and sends the evidence to it. The testing
collector still only reads evidence; rerun the real hooks separately when current
scan evidence is needed. A consistent historical report is never relabelled as a
new security pass. Failed checks remain failed regardless of model advice.

Pre-Test Review evaluates scan implementation and failure blocking; CI/CD
Test Review evaluates test results and evidence completeness. Neither stage
can make an unresolved dependency finding disappear.

Use the existing `human_review.py` only after personally reviewing the actual
assessments, making any accepted improvements and retaining before/after evidence.
A completed review requires an actual model run and a recorded human decision;
both remain pending after this connection-only implementation.

## Targeted verification

Reader tests are intended to cover failed dependency evidence alongside
successful functional tests, missing/invalid inputs, stale hashes or commit
mismatches, and skipped or unrun CI tests. Check the implemented cases in
`tests/test_testing_review.py` and run only that preparation test file with:

```bash
python -m pytest student-2/tests/test_testing_review.py -q
python -m pytest ai-services/tests/test_testing_loop.py -q
```

Passing these tests validates the evidence reader. It is not a security-scan
pass, a GitHub Actions run, a shared-loop review, or release approval.
