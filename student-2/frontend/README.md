# Student 2 Frontend Microservice

HTMX presentation layer for the **Resume and Profile Management** feature.

## Responsibilities

- Display CandidateProfile, Resume, and CandidateSkill data.
- Perform CRUD operations through the Student 2 Backend/API microservice.
- Provide an AI-Mode screen for grounded resume feedback.
- Display Release 1 citations, source excerpts, retrieval confidence, the
  structured MCP tool result and raw model output.
- Allow an optional guidance query and display an explicit insufficient-context
  response with no generated feedback when retrieval has no match.
- Never access SQLite or the database microservice directly.

## Local run

Start the database and backend first, then:

```bash
source .venv/bin/activate
pip install -r student-2/frontend/requirements.txt
python student-2/frontend/app.py
```

Open `http://127.0.0.1:8082`.

## Runtime configuration

- `BACKEND_API_URL`: Student 2 backend URL. Local default: `http://127.0.0.1:5001`.
- `PORT`: Frontend port. Default: `8082`.
- `AI_TIMEOUT_SECONDS`: Maximum wait for the complete feedback request. Default:
  `240`. Keep this above the backend's model timeout plus time for MCP and RAG.

All generated text and source identifiers are escaped by the templates.
Source identifiers are displayed as text; only application-assigned citation
IDs become internal page links. Retrieval confidence is labelled as a
heuristic and does not certify factual accuracy.

The frontend sends `rag_query` with the selected profile/resume IDs and job
requirements to its backend. It does not call MCP, RAG or Ollama directly.
For no-match validation, enter `xyzzzyy` as the guidance query; the result shows
low confidence and that no model was called. Clear this field for the normal
role-and-requirements query.
