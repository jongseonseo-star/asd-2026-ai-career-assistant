# Student 4 Release 1 validation

## Scope

Student 4 adds MCP job context and RAG job guidance to the integrated Job Listing Management feature. The existing shared services are extended; no second MCP/RAG server or containerised AI service is introduced.

The database owns SQLite. Frontend requests go through the backend. MCP reads job records through the database API. RAG retrieves the separate `jobs` corpus and calls the local model. Each generated claim cites a job record and a retrieved guidance source. The backend checks the selected record IDs, source mapping, confidence and no-context behavior before displaying an answer.

## Captured results — 29 September 2026

| Check | Evidence | Result |
| --- | --- | --- |
| Student 4, shared services and Student 2 regression tests | `evidence/tests.txt` | 231 passed with AI services disabled |
| Integrated Compose deployment of Student 4 and shared home | `evidence/compose-ps.txt`, `evidence/compose-logs.txt` | Student 4 frontend/backend/database running |
| Database API and feature readiness | `evidence/database-stats.json`, `backend-ready.json`, `frontend-ready.json` | Successful responses |
| Real MCP protocol through backend | `evidence/mcp-backend.json` | Posting 2, its company and owned skills returned |
| MCP frontend response and browser | `evidence/mcp-frontend.json`, `mcp-ui.png` | Structured context displayed |
| Generated RAG answer through backend | `evidence/rag-backend.json` | Two cited claims, medium confidence |
| RAG frontend and browser | `evidence/rag-frontend.json`, `rag-ui.png` | Claims, source IDs and confidence displayed |
| Unmatched question | `evidence/rag-insufficient-context.json`, `insufficient-context-ui.png` | No claims; low confidence; model not called |
| Shared MCP agentic mode | `evidence/mcp-loop.json` | Checks and both model assessments completed |
| Shared RAG agentic mode | `evidence/rag-loop.json` | Retrieval, generated answer, no-context checks and both assessments completed |
| CI disabling in actual backend image | `evidence/disabled-services.json` | AI disabled; MCP/RAG actions return 503 |
| Existing AI summary route | `evidence/release0-ai-summary.json` | HTTP 200; see quality limitation below |

The runtime database was preserved. It contains 10 companies, 9 postings and 17 skills; posting 1 had already been removed before this work. The live demo therefore uses posting 2. Unit tests use isolated databases and verify the original seed counts and CRUD behavior. No user records were reset to make the demo pass.

The inspected RAG answer correctly states that the selected posting does not explicitly label any skills as required and suggests a practice project for the preferred Flask skill. Its cited guidance is project-authored, not an external authority. `llama3.1:8b` generated the RAG answer; `qwen2.5:0.5b` and `llama3.1:8b` supplied the loop's implementation/review assessments. Review status records automated execution, not human approval.

## Reproduce

Follow [Student 4 startup instructions](../../../student-4/README.md). Refresh the jobs corpus before recording evidence, select an existing posting, and run the shared loop's `mcp` and `rag` modes with `--feature jobs --job-id <id>`.

The final RAG demo query is `What does this posting say about skills, and how can I demonstrate them?`. The unmatched query is `What is the weather in Sydney?`.

## Limitations and remaining submission work

- The local checks demonstrate Student 4 and shared-service compatibility. They do not prove that every group feature works together; the group must perform that final demonstration.
- The updated GitHub Actions workflow has not been pushed or executed on GitHub in this work. The local container check is explicitly labelled and is not a successful GitHub run. Add the real run URL after pushing.
- The legacy direct-AI summary still uses the existing small default model. Its captured output repeats and adds unsupported details. The route is operational, but that output is not evidence of factual accuracy. An 800-token limit prevents unbounded generation. RAG uses a separate cited response contract and was inspected against its sources.
- Citation validation checks reference identities and source coverage, not every statement's meaning. Early live model outputs omitted record citations or misread skill labels. The final prompt distinguishes preferred skills from explicit requirements, and the schema requires both record and guidance citations per claim. Continued human review is needed.
- The small token-hash corpus may miss synonyms. Local server/model availability and speed depend on the demo machine. Services are intended for a trusted local environment and do not provide authentication.
- Human decisions on loop assessments remain pending. Record only the student's actual review decision.
- The group PDF, combined showcase video, live showcase/Q&A and final all-feature integration evidence remain group submission tasks.
