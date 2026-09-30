# Student 4 — Job Listing Management

Jongseon Seo's feature manages companies, job postings and job skills. Release 1 adds job context through the shared MCP server and cited answers through the shared RAG server. Existing CRUD, AI summaries, skill extraction and recommendations remain available.

## Services and request flow

| Service | Local address | Runs in |
| --- | --- | --- |
| Frontend | http://localhost:8404 | Docker |
| Backend | http://localhost:5401 | Docker |
| Database API | http://localhost:5402 | Docker |
| Shared MCP | http://localhost:8765/mcp | Host |
| Shared RAG | http://localhost:8766 | Host |
| Ollama | http://localhost:11434 | Host |

The frontend calls only the backend. The backend calls `job_context(job_id)` through MCP to obtain the current posting, its company and its skills. MCP reads through the database API; only the database service opens SQLite.

For a question, the backend first gets the selected job through MCP, then sends that context and the question to RAG `/answer`. RAG searches the `jobs` corpus and asks Ollama for cited claims. The backend checks the evidence before returning it to the frontend. The UI shows claims, citation IDs, supporting excerpts and confidence. An unmatched question returns insufficient context without calling the model.

## Run the integrated application

From the repository root, prepare the host environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r ai-services/requirements.txt
ollama list
```

Start Ollama if it is not already running. The examples use an installed `llama3.1:8b` model for RAG. In separate terminals, activate the environment and start the two shared services:

```bash
STUDENT4_DATABASE_API_URL=http://127.0.0.1:5402 python ai-services/mcp_server.py --transport streamable-http
```

```bash
OLLAMA_MODEL=llama3.1:8b python ai-services/rag_server.py
```

Start the integrated Compose application:

```bash
AI_SERVICES_ENABLED=true docker compose up --build -d
```

To work only on Student 4 in that same integrated stack:

```bash
AI_SERVICES_ENABLED=true docker compose up --build -d student-4-database student-4-backend student-4-frontend shared-frontend
```

Refresh the reviewed job guidance:

```bash
curl -fsS -X POST http://127.0.0.1:8766/refresh \
  -H 'Content-Type: application/json' -d '{"feature":"jobs"}'
```

Open http://localhost:8404 and expand **Explore this job with sources** on any posting. Use **View job context (MCP)**, then **Ask with sources (RAG)**. Ask `What is the weather in Sydney?` to demonstrate insufficient context.

The standalone alternative is `AI_SERVICES_ENABLED=true docker compose -f student-4/compose.local.yml up --build`. Do not run both stacks on the same ports. Containers use `host.docker.internal`; host services use `127.0.0.1`. No AI services are defined as Compose services. If Docker cannot reach loopback services on a different platform, configure `AI_SERVICES_HOST` for the trusted demo environment.

## Interfaces and boundaries

- MCP `job_context(job_id)` accepts one positive integer, rejects extra arguments and returns `job`, `company`, `skills`, and database `sources`.
- Backend `POST /api/v1/mcp/jobs/<id>/context` returns that structured tool result.
- Backend `POST /api/v1/rag/jobs/<id>/answer` accepts only `{"query":"..."}` (1–2,000 characters). It obtains the job itself; the caller cannot supply records, prompts or a model.
- Shared `/answer` accepts `feature: "jobs"`, `task: "job-guidance"`, `query`, `top_k` and `job_context`. Direct access is a trusted local interface, not an authenticated database lookup.
- Missing records return 404; unavailable services return 503; malformed answers or unknown citations return 502.
- `AI_SERVICES_ENABLED=false` disables MCP/RAG. `OLLAMA_ENABLED=false` disables the existing direct AI functions. Both are set explicitly in Student 4 CI.

## Sources and confidence

Reviewed project-authored guidance is in `ai-services/knowledge/jobs/`. The shared Chroma implementation indexes it separately from resume and interview material. Runtime job records are fetched live and are not copied into the guidance index.

`J1`, `J2`, etc. identify database evidence; `G1`, `G2`, etc. identify retrieved guidance. Every generated claim must cite one supplied record ID and one supplied guidance ID. Confidence comes from retrieval coverage and source authority, not the model's opinion. Current project-authored sources normally produce **medium** confidence. No matching source produces **low** confidence and no generation.

Citation checks establish traceability, not factual correctness. Read the claims against the excerpts. Token-hash retrieval can miss synonyms, the corpus is small, and the local model may still misread a posting. These unauthenticated services are for a trusted local demo.

## Tests and evidence

```bash
python -m pip install -r student-4/backend/requirements.txt pytest
OLLAMA_ENABLED=false AI_SERVICES_ENABLED=false python -m pytest student-4/tests ai-services/tests -q
```

Use a job ID that exists in your database (the captured demo uses `2`):

```bash
python ai-services/agentic_loop.py --mode mcp --feature jobs --job-id 2 \
  --evidence-file docs/release-1/student-4/evidence/mcp-loop.json
python ai-services/agentic_loop.py --mode rag --feature jobs --job-id 2 --timeout 210 \
  --evidence-file docs/release-1/student-4/evidence/rag-loop.json
```

The shared loop retains the existing modes. Student 4 uses its MCP and RAG modes; the older DB/architecture/DevOps collectors still cover Student 2. `--checks-only` is a diagnostic run and does not replace model assessments. Human review remains pending until a person records their own decision.

See [Release 1 validation](../docs/release-1/student-4/README.md) for captured results and outstanding submission work.
