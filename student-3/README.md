# Student 3 - Interview Preparation (Release 2)

Student 3 manages interview practice, mock question generation, candidate responses, and evaluation. Release 2 introduces integration with the shared non-containerised local Multi-Agent Server coordinating Planner, Worker, and Reviewer agents.

## Service components

- `frontend/`: interview practice and feedback interface (HTMX + Jinja/HTML) with selectable AI modes (`multi-agent`, `mcp-rag`, `mcp`, `ai`) and multi-agent status monitoring.
- `backend/`: interview question generation and response evaluation API, connecting to feature database and shared AI services.
- `database/`: interview sessions, questions, responses, and feedback SQLite data API.
- `tests/`: feature contract, unit, and multi-agent integration tests.

## Release 2 Multi-Agent Integration

Release 2 delegates interview preparation and answer evaluation to the shared Multi-Agent Server running on the host (`MULTI_AGENT_SERVER_URL`, default `http://127.0.0.1:8767` on host or `http://host.docker.internal:8767` in Docker).

### Architecture
1. **Planner Agent**: Analyzes candidate target role and interview type, formulating a structured preparation blueprint, competency focus areas, and evaluation rubric dimensions.
2. **Worker Agent**: Synthesizes practical, high-calibre interview questions with evaluation criteria, and generates constructive answer evaluations.
3. **Reviewer Agent**: Audits questions and evaluations against the planner's criteria, providing quality scoring (0-100), itemized strengths/weaknesses, and revision recommendations.
4. **Coordinator Loop**: Executes iterations until approved or max iterations reached, producing a full execution trajectory.

### Backend Endpoints
- `POST /api/v1/interview-sessions/<id>/generate-questions`: supports `"mode": "multi-agent"` (default when AI services enabled).
- `POST /api/v1/interview-questions/<id>/evaluate-answer`: supports `"mode": "multi-agent"`.
- `POST /api/v1/interview-sessions/<id>/multi-agent-prep`: dedicated multi-agent preparation endpoint.
- `POST /api/v1/interview-questions/<id>/multi-agent-evaluate`: dedicated multi-agent answer evaluation endpoint.
- `GET /api/v1/multi-agent/status`: returns health and capability status of the multi-agent server.

## Local verification

```bash
# Run feature and multi-agent integration tests
python -m pytest student-3/tests -v

# Run Ruff security audit (Bandit rules) on Student 3
ruff check --select S student-3
```

## Security Review & Ruff Bandit Audit

Static security analysis (`ruff check --select S student-3`) identified 7 findings across Student 3 feature services. All 7 findings have been reviewed and remediated:

| Rule | Location | Finding Description | Resolution / Architectural Justification |
| :--- | :--- | :--- | :--- |
| **S104** | `backend/app.py` | Possible binding to all interfaces (`0.0.0.0`) | **Resolved**: Refactored host configuration to use `HOST = os.getenv("HOST", "127.0.0.1")`. Local invocation now binds securely to localhost by default. In containerized environments, `ENV HOST=0.0.0.0` is provided via `Dockerfile` and `compose.local.yml` to support Docker bridge networking. |
| **S608** | `database/app.py` (`/api/v1/stats`) | Possible SQL injection vector via table interpolation | **Resolved**: Replaced dynamic table string interpolation with explicit static `SELECT COUNT(*)` queries for `interview_sessions`, `interview_questions`, and `interview_responce`. |
| **S608** | `database/app.py` (`session_detail`) | Possible SQL injection vector via dynamic UPDATE clause | **Resolved**: Converted dynamic `UPDATE interview_sessions` clause assembly into a static parameterized SQL update statement that merges existing record values with supplied fields, eliminating query string construction while preserving partial update semantics. |
| **S608** | `database/app.py` (`question_detail`) | Possible SQL injection vector via dynamic UPDATE clause | **Resolved**: Converted dynamic `UPDATE interview_questions` clause assembly into a static parameterized SQL update statement merging existing fields (`category`, `question_text`). |
| **S608** | `database/app.py` (`response_detail`) | Possible SQL injection vector via dynamic UPDATE clause | **Resolved**: Converted dynamic `UPDATE interview_responce` clause assembly into a static parameterized SQL update statement merging existing fields (`user_answer`, `ai_feedback`, `improvement_tips`, `score`). |
| **S104** | `database/app.py` | Possible binding to all interfaces (`0.0.0.0`) | **Resolved**: Refactored host configuration to use `HOST = os.getenv("HOST", "127.0.0.1")` with container-level override (`ENV HOST=0.0.0.0`), preventing unintended exposure on uncontainerized hosts. |
| **S104** | `frontend/app.py` | Possible binding to all interfaces (`0.0.0.0`) | **Resolved**: Refactored host configuration to use `HOST = os.getenv("HOST", "127.0.0.1")` with container-level override (`ENV HOST=0.0.0.0`), keeping local execution bound to localhost. |

