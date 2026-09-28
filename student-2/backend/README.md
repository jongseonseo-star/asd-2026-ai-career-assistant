# Student 2 Backend/API — Release 0

This Flask service provides the public Resume and Profile Management API.

## Responsibilities

- Expose CRUD endpoints for candidate profiles, resumes, and skills.
- Access candidate data only through the Student 2 Database API.
- Validate client input and preserve upstream HTTP status codes.
- Retrieve controlled profile, resume, and skill context.
- Call Ollama for evidence-based resume feedback.
- Expose health, readiness, and AI runtime status endpoints.

## Local defaults

- Backend: http://127.0.0.1:5001
- Database API: http://127.0.0.1:5002
- Ollama: http://127.0.0.1:11434
- Model: qwen2.5:0.5b
