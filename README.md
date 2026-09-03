# ASD 2026 AI Career Assistant

An integrated Agentic AI application that helps users discover jobs, improve resumes, manage applications, and practise interviews.

## Release 0 scope

- Four student-owned feature areas
- One frontend, backend/API, and database microservice per feature
- CRUD operations through the frontend and APIs
- SQLite data owned by each database microservice
- Ollama integration using an approved open-source LLM
- Shared `Plan -> Act -> Observe -> Adapt` workflow
- Local execution through one Docker Compose configuration
- Student-specific GitHub Actions workflows

> The project specification assumes a five-person team. This repository currently reflects a four-person team and requires tutor approval for that exception.

## Feature ownership

| Student | Feature | Frontend responsibility | Backend/API responsibility | Database responsibility |
| --- | --- | --- | --- | --- |
| Student 1 | Application and Cover Letter Management | Track applications and manage cover letters | Generate tailored cover letters and next actions | Store applications, cover letters, and status history |
| Student 2 | Resume Management | Manage profiles and resumes | Analyse resumes and identify skill gaps | Store candidate profiles, resumes, and skills |
| Student 3 | Interview Preparation | Run interview practice sessions | Generate questions and evaluate responses | Store sessions, questions, responses, and feedback |
| Student 4 | Job Listing Management | Search and manage jobs | Analyse jobs, extract skills, and recommend roles | Store companies, job postings, and job skills |

## Intended request flow

```text
Browser
  -> Frontend microservice
  -> Backend/API microservice
  -> Database API microservice
  -> SQLite

Backend/API microservice
  -> Ollama
  -> Approved LLM
```

Microservices must access another feature's data through its exposed API. They must not open another service's SQLite file directly.

## Repository structure

```text
.
|-- .github/workflows/       Student CI workflows
|-- ai-services/             Shared AI Mode and Ollama integration
|-- docs/
|   |-- architecture/        Architecture diagrams
|   `-- reports/             Technical report material
|-- scripts/                 Build, test, and deployment helpers
|-- shared/frontend/         Shared HTMX home page and common assets
|-- student-1/               Job Listing feature
|-- student-2/               Resume feature
|-- student-3/               Application feature
|-- student-4/               Interview feature
|-- docker-compose.yml       Integrated local application
`-- .env.example             Shared environment variable template
```

Each `student-x` directory contains:

```text
student-x/
|-- frontend/
|-- backend/
|-- database/
`-- tests/
```

## Team workflow

1. Create a feature branch for your work.
2. Commit regularly with meaningful messages.
3. Push the branch and open a pull request.
4. Run and verify the assigned GitHub Actions workflow.
5. Resolve integration issues before merging into `main`.
6. Keep test, Agentic AI, and contribution evidence for the report.

## Local setup

Start Ollama on the host, then run the integrated services currently available:

```bash
cp .env.example .env
docker compose config
docker compose up --build
```

Open the shared home page at `http://localhost:8080`.

Do not commit `.env`, database files, secrets, or generated logs.
