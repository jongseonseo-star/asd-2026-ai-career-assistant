# Student 2 Backend/API — Release 0 and Release 1

This Flask service provides the public Resume and Profile Management API.

## Responsibilities

- Expose CRUD endpoints for candidate profiles, resumes, and skills.
- Access candidate data only through the Student 2 Database API.
- Validate client input and preserve upstream HTTP status codes.
- Retrieve controlled profile, resume, and skill context.
- Call Ollama directly for the preserved Release 0 feedback path.
- In Release 1, retrieve candidate records through MCP and delegate retrieval
  plus local-model generation to shared RAG `POST /answer`; validate source
  IDs and return the structured MCP result for display.
- Expose health, readiness, and AI runtime status endpoints.

## Local defaults

- Backend: http://127.0.0.1:5001
- Database API: http://127.0.0.1:5002
- Ollama: http://127.0.0.1:11434
- Model: qwen2.5:0.5b

## Shared AI configuration

`AI_SERVICES_ENABLED=false` preserves the original direct-database feedback
path. Set it to `true` for the MCP/RAG extension. `MCP_BASE_URL` defaults to
`http://127.0.0.1:8765`, `RAG_BASE_URL` to `http://127.0.0.1:8766`, and
`SHARED_AI_TIMEOUT_SECONDS` to `10` for MCP. RAG generation uses
`RAG_GENERATION_TIMEOUT_SECONDS` (default `210`). Container deployments use
`host.docker.internal` as configured in Compose.

`OLLAMA_ENABLED=false` prevents this backend's direct model calls. CI also sets
`AI_SERVICES_ENABLED=false` to disable calls to shared MCP/RAG. The shared RAG
process has its own `OLLAMA_ENABLED`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`,
`OLLAMA_TIMEOUT_SECONDS` (180 by default) and `OLLAMA_NUM_CTX` settings.

`OLLAMA_NUM_CTX` in the shared RAG process defaults to `8192` for Release 1 generation so the prompt,
source catalogue and output schema fit a larger context than a 4096-token
runtime default. Release 0 does not override the model's context setting.
This is capacity configuration, not a guarantee of model accuracy. Responses
include `generation_metadata` with Ollama's reported `prompt_eval_count`,
`eval_count`, `done_reason` and `total_duration` when available, plus the
configured context size for Release 1. Duration is the runtime's nanosecond
value. The metadata supports diagnosing truncation; it does not prove that all
facts were considered.

## Resume feedback contract

`POST /api/v1/ai/resume-feedback` accepts positive integer `profile_id` and
`resume_id` values plus an optional `job_description` up to 6,000 characters.
An optional `rag_query` (up to 20,000 characters) overrides guidance retrieval;
blank uses the target role and job description. The resume must belong to the
selected profile. No candidate data is modified.

Both modes return `feedback`, `raw_feedback`, `model`, selected IDs and
`context_summary`. Release 1 additionally populates `feedback_sections` with
four named arrays of `{text, citations}` items. `evidence_sources` maps each
ID to actual retrieved text and a source identifier. Candidate IDs are `C1`
(profile), `R1` (resume), and `S1` onwards (skills); `J1` is the optional supplied
job description; `G1` onwards identify retrieved guidance. These source IDs are
assigned by the shared RAG service using `feedback_contract.py`, then checked
by the backend against the MCP records. They cannot be invented by the model.

`confidence` and `confidence_basis` concern guidance retrieval only. Empty
retrieval returns `status: insufficient-context`, no guidance sources, low
confidence, empty feedback sections and `generation_metadata.called: false`.
No model call occurs. Successful generation returns `status: answered` and
`generation_metadata.called: true`. `mcp_result` contains the tool response. An
unavailable MCP/RAG service returns 503, malformed service/model data returns
502, missing records return 404, and input or ownership errors return 400.
The response never substitutes simulated feedback when a dependency fails.

Known-source citation validation, candidate-only strength citations and concise
output limits are enforced. Semantic support still requires human review:
a valid source ID alone cannot establish that an AI claim is true.
