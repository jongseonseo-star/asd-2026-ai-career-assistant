# Shared local AI services

The shared FastMCP server, RAG server and development review loop run on the host alongside local Ollama. Feature frontend, backend and database services run in Docker. Chroma is an embedded local library; it needs no additional server, container, cloud account or embedding model.

Student 2 implements the resume flow through these shared services. Other students' feature code and Compose service settings are outside this change. Existing interview retrieval and `/pipeline` behavior are preserved; this validation does not establish other features' Release 1 completion.

## Start the local services

Run commands from the repository root. Create a virtual environment once, then activate it in each Python terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r ai-services/requirements.txt
```

Start Ollama on the host and inspect installed models with `ollama list`. The examples use `llama3.1:8b` for resume generation and review, and `qwen2.5:0.5b` for implementation assessment. Install missing models before the demonstration; application startup does not download models. Model selection does not guarantee correct feedback.

Start MCP in one terminal:

```bash
STUDENT2_DATABASE_API_URL=http://127.0.0.1:5002 RAG_BASE_URL=http://127.0.0.1:8766 python ai-services/mcp_server.py --transport streamable-http
```

Start RAG in another terminal:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=llama3.1:8b OLLAMA_TIMEOUT_SECONDS=180 OLLAMA_NUM_CTX=8192 python ai-services/rag_server.py
```

Start Student 2 and the shared home page in a third terminal:

```bash
AI_SERVICES_ENABLED=true OLLAMA_MODEL=llama3.1:8b docker compose -p asd-2026-ai-career-assistant up --build -d student-2-database student-2-backend student-2-frontend shared-frontend
```

Open [Student 2](http://127.0.0.1:8082) or the [shared home page](http://127.0.0.1:8080). Do not start another stack on the same published ports. The [Student 2 README](../student-2/README.md) describes its standalone Compose option.

| Connection | Default address |
| --- | --- |
| Host to MCP protocol endpoint | `http://127.0.0.1:8765/mcp` |
| Host to RAG HTTP API | `http://127.0.0.1:8766` |
| Host to Ollama native API | `http://127.0.0.1:11434` |
| Host to Student 2 database/backend/frontend | Ports `5002` / `5001` / `8082` |
| Feature containers to host MCP/RAG/Ollama | `http://host.docker.internal:8765` / `:8766` / `:11434` |

Compose reads `.env`; host Python processes read exported environment variables and do not load that file automatically. Use host addresses for host processes. Shared services bind `127.0.0.1` by default. Verify Docker-to-host connectivity on the demo computer; if its networking requires another interface, set `AI_SERVICES_HOST` deliberately. These unauthenticated local services are intended for a trusted development environment.

## MCP tools and boundaries

The standalone `fastmcp` package provides protocol discovery, typed tool schemas, structured results and `isError` failures. The shared server exposes:

| Tool | Purpose |
| --- | --- |
| `resume_context(profile_id, resume_id)` | Read the current profile, owned resume and skills through the Student 2 database HTTP API, with `db://student-2/...` references. |
| `interview_context(target_role, interview_type="general")` | Preserve the existing bounded interview guidance interface. |
| `refresh_corpus(feature="resume")` | Rebuild one approved local RAG corpus through `/refresh`. |
| `retrieve_context(query, top_k=3, feature="resume")` | Retrieve cited chunks through `/retrieve`. |
| `answer_question(profile_id, resume_id, query, top_k=3, job_description="")` | Fetch owned candidate records through `resume_context`, then request shared RAG resume feedback through `/answer`. |

IDs must be positive integers; `top_k` is an integer from 1 to 5. Missing records, ownership mismatches, invalid inputs and dependency failures remain errors. Tools never open another service's SQLite file. The RAG wrappers accept neither arbitrary file paths nor caller-selected model settings. `answer_question` obtains candidate context itself rather than accepting caller-supplied records.

The Student 2 UI backend calls `resume_context` and then shared `/answer` over HTTP. The three RAG tools also expose the Lab 8 refresh/retrieve/answer sequence through MCP clients, using the same shared RAG implementation.

## Retrieval, refresh and provenance

Resume sources are reviewed project-authored Markdown files in `knowledge/resume/`. The retained interview corpus is defined in `rag_server.py`. Candidate records are fetched live through MCP and are not placed in the guidance vector index.

The Lab 8 retrieval path splits contiguous source text into chunks of at most 80 words, creates deterministic 256-dimensional token-hash embeddings, and persists them in local Chroma with cosine distance. It retrieves candidates, applies meaningful-token overlap and a similarity threshold, ranks by authority and distance, and returns at most `top_k` chunks. These educational embeddings encode token features; they are not a trained semantic model and may miss synonyms.

Results include original chunk text, title, `chunk_id`, stable `source_id`, a source URI such as `repo://ai-services/knowledge/resume/skill-gaps.md#chunk-1`, feature, authority tier, source/corpus versions, indexing time, cosine score and distance. Guidance references identify actual project files and chunks, not external publications or candidate achievements.

Refresh explicitly after reviewing a source change, and before collecting live RAG evidence:

```bash
curl -fsS -X POST http://127.0.0.1:8766/refresh -H 'Content-Type: application/json' -d '{"feature":"resume"}'
curl -fsS http://127.0.0.1:8766/corpus
curl -fsS -X POST http://127.0.0.1:8766/retrieve -H 'Content-Type: application/json' -d '{"query":"resume achievements and skill evidence","feature":"resume","top_k":3}'
```

`POST /refresh` with `{}` refreshes both corpora. It builds a new collection, validates its contents and a real vector query, then switches the active manifest for that corpus. A failed refresh retains the previous collection. First retrieval initializes a missing index using the same validation. Changed source versions or a corrupted stored corpus are rejected until refresh succeeds; stale text is not silently presented as current.

`RAG_DATA_DIR` defaults to `ai-services/data/rag`, containing Chroma, versioned corpus snapshots, an active manifest and timestamped refresh/retrieval audit records. A vector query failure can use an explicitly labelled `lexical_fallback` against validated corpus text, with degraded status and a warning. Evaluation and agentic RAG checks do not count fallback as successful vector retrieval. Initialization or integrity failures return errors.

Confidence describes coverage and authority: no matching context is `low`; matching project guidance is `medium`; `high` requires at least two distinct tier 1/2 sources and healthy vector retrieval. Current authored guidance is tier 3. Confidence is not an accuracy probability, an employment prediction or model self-certainty.

## Grounded answer contract

`POST /answer` accepts `task: "resume-feedback"`, `feature: "resume"`, `query`, `top_k`, `candidate_context` from MCP and optional `job_description`. The shared process controls the prompt, model, schema and source IDs and calls local Ollama. The feature backend must obtain current owned records first. Direct `/answer` access is not an authenticated database lookup.

Responses contain Strengths, Skill Gaps, Recommended Actions and Information Missing, per-item citations, source excerpts, retrieval metadata and generation metadata. Candidate records support candidate claims; job requirements are comparison criteria; retrieved guidance is general advice. Shared RAG and the backend check the response contract and references. This establishes traceability, not whether every claim is true. Review actual output against its sources, particularly claims about missing skills or education.

With no relevant guidance, `/answer` returns `status: "insufficient-context"`, empty generated feedback, low confidence and `generation_metadata.called: false` without calling Ollama. The UI exposes this path through its optional guidance query. `/pipeline` remains a diagnostic/extractive compatibility endpoint. `/retrieve` and `/pipeline` default to the existing interview keyword retrieval when `feature` is omitted; its ranking, source references and confidence behavior are preserved without initializing Chroma. Specify `"resume"` for Student 2's vector retrieval.

`resume_generation.py` intentionally reuses `student-2/backend/feedback_contract.py` and its prompt assets as the resume feature adapter. This keeps citation rules consistent without another framework or a full shared-domain refactor. Run from a complete checkout. Student 4 job generation and frontend integration are described below. Interview generation remains separate.

## Retrieval evaluation and tests

Run the fixed benchmark against an isolated Chroma directory:

```bash
python ai-services/rag_eval.py --data-dir ai-services/data/rag-evaluation --output docs/release-1/student-2/evidence/retrieval-benchmark.json
```

This refreshes real indexes, compares vector retrieval with a lexical baseline, and records manually specified relevant chunks, P@5, R@5, unrelated-query results and corpus versions. P@5 always divides by five even when fewer chunks are returned. Negative queries have no recall denominator and are excluded from recall averages. This small retrieval benchmark does not measure generated-answer accuracy.

```bash
python -m pip install -r student-2/backend/requirements.txt pytest
OLLAMA_ENABLED=false AI_SERVICES_ENABLED=false python -m pytest student-2/tests ai-services/tests -q
```

Tests exercise temporary real Chroma indexes, controlled refresh and failure cases, FastMCP protocol calls and feature contracts. Automated model calls are mocked. Live model, Docker-to-host and frontend demonstrations require separate evidence.

## Shared development review loop

`agentic_loop.py` collects actual observations before requesting model assessments. It never changes code or approves its own advice.

| Mode | Evidence collected | Assessments |
| --- | --- | --- |
| `db` | Live database health, records, required fields and relationships | Implementation model |
| `endpoints` | Backend/frontend readiness, API-to-database consistency, invalid input, 20 timed reads | Implementation model |
| `architecture` | Resolved Compose configuration, live container state, service boundaries and file hashes | Implementation model, then independent review model |
| `devops` | Parsed workflow and actual saved build/smoke-test artifacts | Implementation model, then independent review model |
| `mcp` | Real protocol discovery and structured feature context | Implementation model, then independent review model |
| `rag` | Active corpus, vector retrieval, generated answer with claim/source mappings, no-context behavior and RAG tool registration | Implementation model, then independent review model |

`--mode release0` runs the first four modes. `--mode all` runs all six and is the default. DB, endpoint, architecture and DevOps collectors currently cover Student 2. Resume and job guidance RAG are implemented; interview RAG validation reports its missing generated task rather than claiming success.

For a focused live review with existing matching profile/resume IDs:

```bash
IMPLEMENTATION_MODEL=qwen2.5:0.5b REVIEW_MODEL=llama3.1:8b OLLAMA_BASE_URL=http://127.0.0.1:11434 python ai-services/agentic_loop.py --mode rag --feature resume --profile-id 1 --resume-id 1 --timeout 210 --evidence-file docs/release-1/student-2/evidence/rag-review.json
```

For all modes, first obtain Student 2 workflow artifacts and extract their files directly into `reports/student-2/`, or supply their actual directory. Review the Compose project already running:

```bash
IMPLEMENTATION_MODEL=qwen2.5:0.5b REVIEW_MODEL=llama3.1:8b OLLAMA_BASE_URL=http://127.0.0.1:11434 python ai-services/agentic_loop.py --mode all --feature resume --compose-project asd-2026-ai-career-assistant --compose-file docker-compose.yml --ci-evidence-dir reports/student-2 --timeout 210 --evidence-file docs/release-1/student-2/evidence/all-review.json
```

For the standalone Student 2 setup, use `--compose-project student2-demo --compose-file student-2/compose.local.yml`. Repeat `--compose-file` for any port override file used to start the stack. Change `STUDENT2_DATABASE_URL`, `STUDENT2_BACKEND_URL` and `STUDENT2_FRONTEND_URL` for alternate host ports; MCP separately uses `STUDENT2_DATABASE_API_URL`. Architecture collection reads the existing configuration and containers without restarting them.

DevOps requires `report.json`, `profiles.json`, `resumes.json`, `skills.json`, `database-health.json`, `backend-readiness.json`, `frontend-readiness.json`, `ai-status.json`, `compose-ps.txt` and `compose-logs.txt`. The report identifies the workflow hash, execution source, result and record counts; GitHub artifacts also identify the run URL/ID and commit. Missing or outdated artifacts fail. Clearly labelled `local-ci-equivalent` evidence is supported but is not proof of a successful GitHub run. The [current workflow](../.github/workflows/student-2.yml) is manually dispatched and disables Ollama/MCP/RAG in CI. Its presence does not establish a successful run of this revision.

`IMPLEMENTATION_MODEL` and `REVIEW_MODEL` configure assessment roles independently of the RAG answer model. `--timeout` applies to each request, so all modes can take several minutes. `--checks-only` explicitly skips assessments for diagnostics and is not a complete agentic review. Evidence records exact model inputs/outputs, completion metadata, word counts, timing and checks. Candidate context and per-claim citation mappings stay intact in review input; bounded non-semantic excerpts are labelled.

Failed deterministic checks stay failed regardless of model advice. Exit 0 means requested automated checks and required model calls completed, not semantic correctness, human approval or complete group integration. The human decision initially remains pending. After personally reviewing evidence, making any accepted improvement and retesting, record the actual decision with `human_review.py`: supply `--evidence-file`, a new `--output`, `--reviewer`, `--decision` (`accept`, `partially-accept` or `reject`), `--rationale`, and existing `--before`/`--after` files or evidence URLs. The command preserves execution evidence and records a separate decision; it never fabricates acceptance.

## Student 4 job guidance

Student 4 extends the same shared servers with `job_context(job_id)` and a separate
`jobs` knowledge corpus. Set `STUDENT4_DATABASE_API_URL` to the host address of its
database API (default `http://127.0.0.1:5402`). The tool returns only the selected
posting, its company, its skills and their database references.

`refresh_corpus` and `retrieve_context` also accept `feature="jobs"`. Shared
`POST /answer` supports `task="job-guidance"`, `feature="jobs"`, `query`, `top_k`
and `job_context`. The feature backend obtains that context through MCP before
calling RAG. `job_generation.py` uses Student 4's `job_contract.py` and prompt to
check cited claims without changing the resume answer contract.

The shared loop accepts `--feature jobs --job-id <id>` in MCP and RAG modes.
See [Student 4](../student-4/README.md) for startup, boundaries and evidence.
