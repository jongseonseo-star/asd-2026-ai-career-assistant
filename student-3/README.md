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
python -m pytest student-3/tests -q
```
