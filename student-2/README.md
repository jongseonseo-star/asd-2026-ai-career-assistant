# Student 2 — Resume and Profile Management

The frontend manages profiles, resumes and skills; the backend accesses the owning database API and provides resume feedback. SQLite stays inside the database service. Release 0 CRUD and original AI feedback remain available alongside Release 1.

## Choose an analysis mode

The **Analysis mode** selector in the AI workspace exposes three paths:

| UI selection | API `mode` | Behavior |
| --- | --- | --- |
| AI Mode — original feedback | `release0` | Read candidate records through the database API and generate feedback using the backend's local Ollama configuration. |
| MCP — inspect candidate records | `mcp` | Call shared `resume_context`, check ownership and show structured records and sources. No model is called. |
| RAG — feedback with sources | `mcp-rag` | Obtain current records through MCP, retrieve local Chroma guidance and generate cited feedback inside shared RAG. |

Set `AI_SERVICES_ENABLED=true` to enable MCP and RAG. Original mode remains selectable. Disabled shared services leave the original path as the default; enabled but unavailable dependencies produce a visible error rather than a result labelled as successful MCP/RAG.

The status panel checks backend/database availability and the backend's configured **Release 0 model**. It does not pre-validate MCP/RAG connectivity. Each result identifies its mode and model; `generation_metadata.called` distinguishes generation from MCP-only or insufficient-context responses. A configured model name is not proof that a model ran successfully.

## Run locally

Follow [shared service setup](../ai-services/README.md#start-the-local-services) to create a Python environment and start Ollama, MCP and RAG in separate terminals. All commands below run from the repository root. Shared examples use `llama3.1:8b`, which must already be installed.

For this feature alone:

```bash
AI_SERVICES_ENABLED=true OLLAMA_MODEL=llama3.1:8b docker compose -p student2-demo -f student-2/compose.local.yml up --build -d
```

Open [Resume Management](http://127.0.0.1:8082). Backend and database ports are 5001 and 5002. If root Compose already runs Student 2, use that instance rather than starting a conflicting copy. MCP and RAG remain host processes; containers reach them through `host.docker.internal`. Host MCP reaches the database at `http://127.0.0.1:5002` by default.

Configure the model separately on shared RAG for RAG answers and on the backend for original AI Mode. Host Python processes do not automatically load Compose's `.env`. RAG generation timeout defaults to 180 seconds, backend RAG timeout to 210 seconds and frontend AI timeout to 240 seconds. MCP-only uses `SHARED_AI_TIMEOUT_SECONDS` (default 10).

## Evidence and retrieval behavior

MCP reads the selected profile, owned resume and skills through the database HTTP API and returns `db://student-2/...` references. The backend passes these records, job description and guidance query to shared RAG's bounded `resume-feedback` task. RAG retrieves approved project guidance using deterministic 256-dimensional embeddings and local Chroma, then calls the configured local model.

Feedback has four sections: Strengths, Skill Gaps, Recommended Actions and Information Missing. The UI shows per-item references, source excerpts, retrieval confidence, raw output and the structured MCP result. Candidate records support candidate claims; job requirements are comparison criteria; project-authored guidance is general advice. Backend and RAG validate output structure and known source IDs. References make claims inspectable but cannot guarantee factual correctness. Check advice about missing skills or education against the actual records before the demonstration.

Current guidance sources are authored project material: confidence is medium when relevant context is found and low when none is found. High confidence requires multiple qualifying authoritative sources. It is not a model probability or employment prediction. Chunk references include `#chunk-1` and subsequent chunk numbers and preserve the original excerpt.

After reviewing edits to `ai-services/knowledge/resume/*.md`, refresh explicitly:

```bash
curl -fsS -X POST http://127.0.0.1:8766/refresh -H 'Content-Type: application/json' -d '{"feature":"resume"}'
```

Changed source versions are rejected until refresh succeeds. [Shared documentation](../ai-services/README.md#retrieval-refresh-and-provenance) explains versions, audits, degraded fallback and P@5/R@5 evaluation. The normal path uses vectors; deterministic token embeddings still have limited synonym understanding.

For an insufficient-context demonstration, select **RAG — feedback with sources** and enter `What is the weather in Tokyo today?` in **Resume guidance query**. The UI should show **Insufficient context**, low confidence, the MCP result and that no model was called. Clear the query to retrieve using the target role and job description. The API exposes the same optional `rag_query`, bounded to 20,000 characters.

Shared `resume_generation.py` intentionally reuses this feature's `feedback_contract.py` and prompt assets as a feature adapter, keeping citation rules consistent without a full framework refactor. Run RAG from a complete checkout. Student 1, 3 and 4 still need their own completed Release 1 integration.

## Verify and capture evidence

With the shared virtual environment activated:

```bash
python -m pip install -r student-2/backend/requirements.txt -r ai-services/requirements.txt pytest
OLLAMA_ENABLED=false AI_SERVICES_ENABLED=false python -m pytest student-2/tests ai-services/tests -q
```

Automated tests check ownership, original mode compatibility, MCP/RAG contracts, refresh/retrieval, invalid citations, empty context and UI rendering. Model calls are mocked; tests do not establish actual generated-answer quality. For a live demonstration, use a real profile and one of its resumes, exercise all three choices and inspect claims against sources. An answered RAG response includes `mode: "mcp-rag"`, `evidence_sources`, `feedback_sections`, `raw_feedback`, `mcp_result` and `generation_metadata.called: true` with `service: "shared-rag"`.

The [shared loop](../ai-services/README.md#shared-development-review-loop) supports DB, endpoint, architecture, DevOps, MCP and RAG reviews. `--mode all` needs running Compose services and actual CI artifacts. For this standalone stack use `--compose-project student2-demo --compose-file student-2/compose.local.yml` plus the actual `--ci-evidence-dir`. Capture assessments, then record a real human decision and before/after retest evidence; automated success is not human acceptance.

The [Student 2 workflow](../.github/workflows/student-2.yml) is manually dispatched. It tests, builds and smoke-checks with `OLLAMA_ENABLED=false` and `AI_SERVICES_ENABLED=false`, then uploads evidence including run identity and workflow hash. Verify a run for the current revision separately; local results do not prove GitHub Actions passed.
