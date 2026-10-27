# ChromaDB: documented unresolved dependency findings

Date: 22 October 2026 (Australia/Sydney)

Owner: Tomohisa Tamao — Testing / Security coordination

Status: **Documented, unresolved. The dependency audit remains FAIL.**

## Decision and assessment scope

For the current coursework milestone, retain the functioning shared local RAG implementation and document the unresolved Chroma findings. Do not replace the vector store solely to obtain a clean scan before the demonstration. This is a documentation decision, not a finding that Chroma is patched, a declaration that the dependency is safe, or an approval to bypass a failed commit hook.

The current [Assessment 3 Individual Responsibilities](https://canvas.uts.edu.au/courses/39716/assignments/267943) requires each student to run and maintain security scans for their contribution and to “resolve or document relevant findings”. This note supports that documentation requirement. It does not guarantee a mark or override the separate pre-commit execution and evidence criteria.

## Observed audit result

The real pip-audit 2.10.1 run started on 22 October at 14:06:58 Sydney time. It resolved 127 packages and reported ChromaDB 1.5.9 from the shared `ai-services/requirements.txt` range `chromadb>=1.5,<2.0`.

Four distinct finding IDs were retained: **PYSEC-2026-311, PYSEC-2026-3813, PYSEC-2026-3814 and PYSEC-2026-3815**. There are five entries because PYSEC-2026-311 appears twice. All recorded `fix_versions` lists are empty. The same shared dependency is flagged in all three student scopes; these are not twelve different vulnerabilities. The audit exited with code 1 and `passed: false`.

The official advisory pages checked on 22 October still list ChromaDB 1.5.9 as affected and no patched version:

| Advisory | Reported concern |
|---|---|
| [GHSA-f4j7-r4q5-qw2c / CVE-2026-45829](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | Code execution through malicious model configuration during server-side collection creation. |
| [GHSA-2wm9-hf6c-p5cr / CVE-2026-45830](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | Insufficient tenant authorization for collection access. |
| [GHSA-36p7-vc44-83pf / CVE-2026-45833](https://github.com/advisories/GHSA-36p7-vc44-83pf) | Code execution through malicious model configuration during a permitted collection update. |
| [GHSA-xph7-9rjv-w5fr / CVE-2026-45831](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | RBAC permissions are not correctly restricted to the tenant, database or collection. |

## Project applicability and remaining uncertainty

The reviewed `rag_retrieval.py` uses an embedded persistent client, explicitly sets `embedding_function=None`, and supplies locally computed vectors. The reviewed RAG HTTP routes do not accept model-repository settings or expose Chroma collection configuration updates. The application does not use Chroma server RBAC as its user authorization boundary.

These source observations differ from the server attack paths described above. They do **not** remove the vulnerable package or prove those paths are unreachable under every runtime configuration. This review does not establish the safety of separately launched Chroma services, externally modified stored configuration, future multi-tenant use, or actual network exposure. Functional RAG and CRUD successes are not security remediation evidence.

## Evidence and follow-up

- Shareable audit copy: [Student 2 dependency audit](evidence/security-dependencies.json). Its raw source is `reports/demo-20261022/runtime-security/student-2/security/dependencies.json`; equivalent Student 3 and Student 4 reports are retained in their own scope folders.
- Existing applicability detail: [Student 2 security documentation](../../../student-2/SECURITY.md).
- Shareable Pre-Test evidence: [model review](evidence/pre-test-live.json), [separate human decision](evidence/pre-test-human-decision.json), and [post-review saved-evidence check](evidence/pre-test-post-review-evidence-check.json). The raw records remain under `reports/demo-20261022/`. This note does not alter any decision or model output.
- [Evidence scope and privacy substitutions](evidence/README_EN.md) and [original/copy SHA-256 manifest](evidence/manifest.json) distinguish the shared copies from historical originals. Embedded evidence hashes remain hashes of the original bytes; sanitized copies have their own manifest hashes.
- Reassess when a verified fixed release is available or when dependency versions, Chroma configuration, stored data, authorization or service exposure changes. Any remediation requires a fresh dependency audit and affected RAG regression checks.
- Keep the dependency result as FAIL in the report and demonstration. No vulnerability IDs have been ignored; no dependency, hook or scan implementation is changed by this note. The current commit gate therefore remains unresolved.

## Suggested demonstration explanation

“The dependency audit completed and reported four unresolved ChromaDB findings. I documented the affected version, our embedded usage, the limits of the applicability review and the follow-up actions. The audit remains failed; this is evidence of detecting and reporting the issue, not evidence that it has been fixed.”
