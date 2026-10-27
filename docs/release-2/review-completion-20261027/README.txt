Group 19 / ASD Assessment 3 / Release 2 evidence
Prepared 27 October 2026. This collection preserves the reviewed evidence and its limits.

Status
- The user selected RETURN FOR REWORK, recorded separately in
  reviews/human-release-decision.json. This individual decision does not assert
  team agreement or acceptance of additional later findings. No release approval is
  inferred from completed model calls, successful CI or cloud deployment.
- Three saved development report reviews completed: MA Workflow, Testing
  Report attempt 2, and Cloud Deployment attempt 2. Each contains actual Qwen
  2.5:7b and Llama 3.1:8b HTTP 200 outputs and retained request/completion data.
- Their PASS fields mean selected-input integrity and model completion only.
  Source FAILs, INCOMPLETE records and unverified scope remain unresolved.
- Latest local pre-commit: own-source Ruff and secrets PASS for Students 2/3/4;
  dependency audit completed FAIL for all three. Each audited 122 packages and
  retained the same Chroma 1.5.9 findings (five entries, four distinct IDs).
- A separate Student 2 plus shared-source Ruff scan remains FAIL: 16 findings.
  Existing flagged statements and model-review omissions require human review.
- The latest pre-commit results are a separate supplement, absent from the
  frozen model inputs. They did not become a completed model reassessment.

Navigation (paths are relative to this folder)
0. reviews/human-release-decision.json
   Tomohisa Tamao's actual RETURN FOR REWORK choice, verbatim user response,
   target revision, evidence presented before the choice and remaining risks.
   This is not conditional approval, a security waiver or a fabricated approval.
   Testing attempt 2 is a separate supplement, not the basis of that choice.
1. reviews/diagnostics/post-review-validation.json
   Mechanical audit of current manifests, report text, reference hashes, both
   models' complete inputs, completion/word/context guards and semantic limits.
2. reviews/output/ma_workflow.json
   reviews/output/testing_report-attempt2.json
   reviews/output/cloud_deployment-attempt2.json
   The selected completed raw executions; matching .log files retain stdout.
3. reviews/input/
   Exact selected reports and manifests. Each manifest's relative references
   resolve within this folder when evidence/ and reviews/ retain this structure.
4. reviews/output/cloud_deployment.json
   Preserved failed initial cloud review: reviewer returned 46 words against an
   added 40-word gate. Later report modes use the existing general 80-word limit.
   Do not replace this original attempt or describe it as completed successfully.
5. evidence/security-current/summary.json
   Latest copied nine pre-commit reports, timestamps, hashes, scope, dependency
   details and verification that recorded pre-hook source hashes still match.
   evidence/security-current/pre-commit-current.log preserves the actual log.
   Student reports are under student-2/security/, student-3/security/ and
   student-4/security/ inside evidence/security-current/.
6. reviews/diagnostics/current-source-security/student-2/security/
   Separate current Student 2 plus shared-source Ruff FAIL and secrets PASS.
   evidence/github/shared-source-scan-audit.json explains baseline comparison.
7. evidence/github/ and evidence/local/
   Saved GitHub execution/artifact evidence, cloud observations and historical
   local/application MA evidence. Historical dates and revision limits remain.
   evidence/security/ preserves historical security files unchanged.
8. reviews/diagnostics/report-review-tests.xml and report-review-tests.log
   96 passing offline regression tests, using fixtures and mocked transport.
   These tests are not fresh application, security, cloud or model evidence.

Important limits
- The Testing attempt 2 models did not mention the fresh shared Ruff 16 findings
  despite receiving that report text. A recommendation to rerun a dependency
  scan is verification advice; a rerun alone does not remediate a vulnerability.
- Confirmed live CRUD is Student 2 only. Other members' write CRUD and the live
  deployed SHA remain unverified. AI-disabled cloud CRUD is the baseline;
  optional cloud AI is not required to turn this evidence into an approval.
- Dependency requirement auditing does not prove vulnerable AI packages are
  installed in the cloud baseline. Empty recorded fix-version lists do not
  establish whether a fix exists now.
- Raw model execution snapshots keep human_decision=pending because they were
  written before the separate human release judgment. Do not edit them to add
  acceptance. The final judgment must identify its actual scope and rationale.
- Absolute original-machine paths inside raw execution JSON are provenance.
  Use this navigation list and input manifests for portable file navigation;
  keep the raw evidence unchanged.

Review tooling and saved execution provenance
The review implementation is included at ai-services/ in the repository root.
See ai-services/REPORT_REVIEWS.md for setup, the input contract and new runs.
The saved reviews were executed from modified, uncommitted tooling based on
3649ed5d25fa9de6cc601e1a69e922a004a81946. The source hashes in
reviews/tool-source/provenance.json identify the exact executed files.
Publishing the tooling later does not change that execution history or make
the evidence a fresh test of the publication commit. The reviewed application
target remains 3649ed5 and deployment run 40402532547.

Publication authorization and limits
publication-authorization.json records the user's approval for one preservation
commit with only group-dependency-audit skipped, followed by a dedicated branch
and draft pull request. Normal Ruff and secrets hooks remain enabled. The
completed dependency FAIL reports are retained in evidence/security-current/.
This exception allows saving the evidence; it is not a dependency remediation,
release approval, permission to merge, or permission to deploy.

Portable submission package
Group19_Release2_Evidence.zip contains the final Word and PDF, this README,
evidence/, reviews/, the nine-file source-changes/ overlay, and a SHA-256 index.
The repository collection contains the evidence and reviews; the review source
changes are at their normal repository paths. The finalized Word/PDF are local
submission artifacts and are not included in this repository collection.
Keep the evidence/reviews directory structure and failed attempts unchanged.
Raw evidence paths describe the original machine; use the manifests and the
navigation above to locate portable copies. A new review must use a new output
filename and must not overwrite a saved execution or human decision.
