# ASD 2026 AI Career Assistant

A group application for managing applications, improving resumes, practising interviews and exploring jobs. Each feature owns its frontend, backend/API and database service. Services access one another's data through APIs rather than opening another service's SQLite file.

## Current Release 1 scope

Student 2 provides profile/resume/skill CRUD and three selectable analysis paths: original local AI feedback, MCP candidate-record inspection without generation, and shared RAG feedback with references. Shared FastMCP and RAG run on the host with Ollama. RAG uses local Chroma, deterministic 256-dimensional embeddings, source chunks, controlled refresh, confidence, no-context handling and a P@5/R@5 retrieval benchmark.

The shared development loop implements DB, endpoint, architecture, DevOps, MCP and RAG evidence collection and model assessment. Its Release 0 collectors cover Student 2; human decisions are recorded separately after review and retesting. Automated success does not guarantee answer correctness or complete group integration.

Student 1, 3 and 4 Release 1 integration remains unfinished. Existing services and interview compatibility routes do not establish that every feature uses generated shared RAG. The Student 2 GitHub workflow must be run and its artifacts checked separately; this README does not assert a successful GitHub run for the current revision.

## Feature ownership

| Student | Feature | Frontend | Backend/API | Database |
| --- | --- | --- | --- | --- |
| Student 1 | Applications and cover letters | Track applications and cover letters | Tailored letters and next actions | Applications, letters and status history |
| Student 2 | Resume and profile management | Manage profiles, resumes and skills | Resume analysis and skill gaps | Candidate profiles, resumes and skills |
| Student 3 | Interview preparation | Interview practice sessions | Questions and response feedback | Sessions, questions, responses and feedback |
| Student 4 | Job listings | Search and manage jobs | Job analysis, skills and recommendations | Companies, postings and job skills |

## Local setup

Docker Compose starts the currently available feature services and shared home page. Local AI processes start separately. From the repository root:

```bash
docker compose -p asd-2026-ai-career-assistant config
docker compose -p asd-2026-ai-career-assistant up --build -d
```

Open the [shared home page](http://127.0.0.1:8080) or [Student 2](http://127.0.0.1:8082). Compose defaults to the original AI path; Ollama must be running with the configured model installed for generated feedback.

For Release 1, follow the complete [shared AI setup](ai-services/README.md#start-the-local-services), then start the feature backend with `AI_SERVICES_ENABLED=true`. This enables MCP and RAG choices while preserving original AI Mode. See [Student 2 instructions](student-2/README.md) for its standalone stack, UI demonstration and source inspection.

Use `.env.example` as a reference when creating `.env`. Compose loads it; host Python processes do not load it automatically. Containers use `host.docker.internal` for local AI services; host processes normally use `127.0.0.1`. Do not start two stacks on the same ports, or commit `.env`, local databases, secrets or runtime logs.

## Review and validation

The [shared service README](ai-services/README.md) documents MCP tools, corpus refresh, retrieval evaluation, generated-answer boundaries, tests and the development loop. The loop accepts `--mode db`, `endpoints`, `architecture`, `devops`, `mcp`, `rag`, `release0` or `all`. An all-mode run requires the actual running Compose project/files and a CI artifact directory; use the documented command rather than assuming missing evidence will pass.

The [Student 2 workflow](.github/workflows/student-2.yml) runs manually with model/shared AI calls disabled, collects Docker smoke-test evidence and uploads its report. Review the actual run and commit identity. Model calls are verified separately on the demo computer. Check generated claims against cited records and retain the human decision, any changes and retest evidence.

## Repository structure

| Path | Purpose |
| --- | --- |
| `ai-services/` | Shared MCP, local Chroma/RAG, feature generation adapter, review loop, prompts and tests |
| `student-1/` … `student-4/` | Student-owned frontend, backend, database and tests |
| `shared/frontend/` | Shared home page and common assets |
| `.github/workflows/` | Student validation workflows |
| `docs/` | Architecture, report and release evidence |
| `docker-compose.yml` | Available feature microservices and shared frontend |

Develop on a feature branch, review changes through a pull request, run the relevant workflow, resolve group integration issues and preserve contribution evidence before merging.
