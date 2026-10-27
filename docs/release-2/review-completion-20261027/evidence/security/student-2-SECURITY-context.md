# Group pre-commit security checks

Ruff security rules, detect-secrets, and pip-audit run through real pre-commit
hooks. The common CLI calls the same scan functions as the retained Student 2
pytest entrypoints. Security tools remain separate from the endpoint tests.

## Scope

- The hooks select all active members: `student-2`, `student-3`, `student-4`.
  Each receives separate results; a failure in any selected scope fails the hook.
- Ruff: selected students' Python code, security `S` rules only. Student 2 keeps
  its existing policy; other scopes use `scripts/security-ruff.toml`.
- Secrets: Git-tracked and non-ignored untracked files in the selected scope; no online
  verification of candidate secrets. Ignored runtime data and local environments
  are not part of this source scan.
- Dependencies: each selected student's backend, frontend, and database requirements plus
  `ai-services/requirements.txt`, because the feature uses that shared AI runtime.
  Source and workflows belonging to other students are not modified by the scanner.
- Shared AI source is an explicit `--include-shared` option, not part of default
  source coverage. Shared AI dependencies are always included in the audit.

The dependency audit resolves the current requirement ranges, including transitive
dependencies. It does not prove the versions already installed in a Docker image
are identical. No vulnerability IDs are ignored and no automatic fixes are applied.

## Install and run

Run from the repository root with Python 3.12 available. A separate ignored
environment keeps these tools apart from the existing root `.venv`:

```bash
python3.12 -m venv student-2/.venv
student-2/.venv/bin/python -m pip install -r student-2/security-requirements.txt
student-2/.venv/bin/python -m pre_commit install --install-hooks
student-2/.venv/bin/python -m pre_commit run --all-files
```

On Windows use `py -3.12` to create the environment and
`student-2\.venv\Scripts\python.exe` in place of `student-2/.venv/bin/python`.
The hooks use the platform-independent `python scripts/security_checks.py` entrypoint.
Do not remove this environment while the installed Git hook refers to it.

For a selected student's checks without a commit:

```bash
student-2/.venv/bin/python scripts/security_checks.py --students student-2 --scan all
```

Use `--students student-3 student-4` to select other members, `--scan ruff` or
`--scan secrets` for an individual scan, and `--include-shared` to include AI source.
`--report-root /absolute/archive` writes distinct `student-N/security` directories.
These selected-scope commands do not change the all-member commit hooks.

`--all-files` checks the current working tree. On an actual commit, pre-commit
temporarily hides unstaged tracked changes so the staged code is checked. Review
and stage the intended files before committing. No commit is needed to run checks.

## Evidence and failure behavior

Each scan writes JSON under `logs/student-N/security/` (ignored by Git), or the
directory named by `STUDENT2_SECURITY_REPORT_DIR` (likewise STUDENT3/STUDENT4).
The Student 2 report schema and default directory remain compatible. Reports include
UTC time, tool/Python versions, input hashes, findings, and pass/fail status.
Dependency evidence includes resolved package versions and vulnerability IDs.
Secret evidence includes only file, line and detector type, never values or source.
Archive evidence for a particular revision before a later scan overwrites it.

Findings, missing tools, invalid results, timeouts, or incomplete dependency audits
fail the hook. A successful detect-secrets process is not sufficient: its findings
must also be empty. A blocked commit must be investigated, not bypassed.

## Reviewed exceptions

- Three `S104` line exceptions retain Docker-required `0.0.0.0` binding; debug
  remains disabled. This is not an instruction to expose services publicly.
- One `S608` line exception covers the database summary's table identifier, which
  comes only from its fixed local list. User data still uses SQL parameters.
- The htmx `integrity` attribute is a public checksum, not a credential. Its one-line
  Jinja allowlist comment leaves the checksum and rendered script attributes intact.
- `S101` is ignored in test files. The legacy Student 2 policy also allows it in
  `security_checks.py`; the scanner now uses an explicit exception, including under `python -O`.

## Initial dependency blocker

On 2026-10-19 UTC (19 October in Sydney), the audit resolved ChromaDB 1.5.9
from the shared AI requirements and reported PYSEC-2026-311, PYSEC-2026-3813,
PYSEC-2026-3814 and PYSEC-2026-3815. The service returned one duplicate entry
and no fixed versions. The dependency hook remains failing; these IDs are not
suppressed. Shared dependencies were not changed. Review remediation with the
shared AI owner and rerun the audit before treating the security gate as passed.

This is local pre-commit evidence, not a GitHub Actions run, deployment approval,
or completion of TestingReportReview.

## Chroma applicability review - 19 October 2026 (Australia/Sydney)

The retained raw audit contains five entries for four distinct findings; the
duplicate is PYSEC-2026-311. The aliases below come from that audit, not a name
match. Its `fix_versions` lists are empty. This records the observed result;
it does not establish that no patch will become available.

| Audit ID and advisory | Reported attack condition | Evidence in the reviewed project | Remaining limit |
|---|---|---|---|
| PYSEC-2026-311 / CVE-2026-45829 / [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | Unauthenticated collection creation through Chroma's server API accepts a malicious model repository and `trust_remote_code=true`. | `ai-services/rag_retrieval.py` uses embedded `PersistentClient`; collection creation sets `embedding_function=None` and supplies locally computed vectors. The project RAG routes do not accept model-repository or remote-code settings. | A separately launched Chroma server, changed runtime settings, or untrusted persisted configuration must be checked on the actual demo machine. |
| PYSEC-2026-3813 / CVE-2026-45830 / [GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | An authenticated Chroma server user can access another tenant's collections because authorization is insufficient. | The reviewed path uses one embedded store and does not configure a Chroma authenticated, multi-tenant server. | This does not prove application-level user isolation or the safety of any separately deployed service. |
| PYSEC-2026-3814 / CVE-2026-45833 / [GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf) | A user with collection-update permission supplies a malicious model repository with remote-code execution enabled. | The reviewed application creates its own collections and supplies explicit vectors for insertion and queries; its HTTP routes do not expose Chroma collection-configuration updates. | Previously stored or externally modified collection configuration remains relevant; the live demo store has not been inspected. |
| PYSEC-2026-3815 / CVE-2026-45831 / [GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | `SimpleRBACAuthorizationProvider` checks a permission without correctly restricting its tenant/database/collection scope. | The reviewed embedded-client path does not configure this provider or use Chroma RBAC as an application authorization boundary. | A future server/RBAC deployment requires a new assessment; the package finding remains present. |

Supporting source locations are `ai-services/rag_retrieval.py` (`embed_texts`,
`CorpusIndex.client`, `refresh`, `retrieve`) and `ai-services/rag_server.py`
(`/refresh`, `/answer`, and the startup host setting). The default RAG host is
`127.0.0.1`, but `AI_SERVICES_HOST` can override it. A loopback default is not
evidence of the host actually used in a running process.

### Environment and stored-data evidence

- The retained test environment `/private/tmp/asd-student2-release2-py312` uses
  Python 3.12.12 and ChromaDB 1.5.9. This matches the audit's resolved Chroma
  version. The saved 209-test result is historical functional-test evidence,
  not a fresh security pass or proof of the demo runtime.
- Three historical test stores were inspected under
  `/private/tmp/asd-student2-baseline-rag`,
  `/private/tmp/asd-student2-final-rag`, and
  `/private/tmp/asd-student2-security-regression-rag`. Each had one resume
  collection with `config_json_str={}`; no external embedding model or
  `trust_remote_code` setting was present in those inspected configurations.
- The live demo RAG process, its effective host/environment settings and its
  active store are still unverified. These historical test stores cannot
  establish the state of that environment.

The reviewed source and historical stores do not demonstrate the published
attack paths. This is a limited applicability assessment, not a declaration
that ChromaDB 1.5.9 is fixed, a false positive, or safe in every deployment.
The dependency hook remains failing; no vulnerability IDs are ignored, and
no dependency, shared AI code, or commit policy is changed by this document.
Keep the raw findings and re-assess after a verified remediation or a change
to dependencies, server exposure, authorization, or stored configuration.

### Course alignment and next integration boundary

[Lab 8, section 4](https://github.com/Georges034302/asd-labs/blob/main/Lab_08_RAG_and_Enterprise_Context_Pipelines.md#4-rag-pipeline-development)
uses Chroma with a local persistent client.
[Lab 11, section 4](https://github.com/Georges034302/asd-labs/blob/main/Lab_11_Testing_Deployment_and_Operations.md#4-testing-implementation)
runs the three scans through pytest and blocks commits on failure. Its sample
does not provide a dependency-vulnerability waiver policy.
[Lab 11, section 7](https://github.com/Georges034302/asd-labs/blob/main/Lab_11_Testing_Deployment_and_Operations.md#7-agentic-loop-integration)
focuses Pre-Test Review on test implementation and scan coverage; CI/CD Test
Review evaluates results and evidence. A review may record a blocker without
turning a failed scan into a pass.

The Student 2 evidence collector, prompts and CI result capture preserve this
blocker. The existing shared loop now connects the explicit `pre_test` and
`cicd_test` modes; connection checks do not run the models or establish a fresh
security pass. A real model review, human decision and CI run remain separate
work. See [TESTING_REVIEW.md](TESTING_REVIEW.md).

### Demonstration integration exception - 22 October 2026

The current [Assessment 3 requirements](https://canvas.uts.edu.au/courses/39716/assignments/267943)
were checked on 22 October. They allow relevant security findings to be resolved
or documented, and require evidence in the project as well as the technical report.
Documentation does not establish a passing audit or marking approval.

The retained [completed dependency audit](../docs/release-2/student-2/evidence/security-dependencies.json)
ran at 03:06 UTC (14:06 Sydney) on 22 October. It resolved ChromaDB 1.5.9,
reported the same four distinct findings, and exited with code 1. The later
ordinary commit attempt at approximately 08:24-08:25 UTC passed the group Ruff
and secret scans, but its dependency audits ended with `JSONDecodeError`.
Those later audits were incomplete; they did not independently re-confirm the
four findings. The ordinary commit was blocked and no commit was created.

The contributor reported the team leader's approval to commit after the proposed
one-time exception was discussed. This demonstration-branch commit therefore
uses `SKIP=group-dependency-audit` for this invocation only. Ruff and secret
scans still run. The hook configuration is unchanged; future commits retain
the dependency gate. No finding is ignored or marked fixed. This exception
does not satisfy Lab 11's all-scans-pass condition and does not itself approve
a main-branch merge, deployment, or a mark.

The all-member, always-run scope and strict handling of incomplete dependency
collection are implementation choices. Auditing the shared dependency in three
student scopes does not create twelve distinct Chroma vulnerabilities.

[Selected historical evidence](../docs/release-2/student-2/evidence/README_EN.md)
preserves the original scan and human-review outcomes. GitHub CI and CI/CD Review
for this commit remain outstanding at commit preparation.
