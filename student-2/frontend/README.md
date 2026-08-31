# Student 2 Frontend Microservice

HTMX presentation layer for the **Resume and Profile Management** feature.

## Responsibilities

- Display CandidateProfile, Resume, and CandidateSkill data.
- Perform CRUD operations through the Student 2 Backend/API microservice.
- Provide an AI-Mode screen for grounded resume feedback.
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
- `AI_TIMEOUT_SECONDS`: Maximum wait for Ollama feedback. Default: `180`.
