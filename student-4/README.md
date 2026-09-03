# Student 4 — Job Listing Management

Release 0 implementation owned by Jongseon Seo.

## Services

- Frontend: `http://localhost:8404`
- Backend/API: `http://localhost:5401`
- Database API: `http://localhost:5402`
- Ollama: host runtime at `http://localhost:11434`

The database service exclusively owns its SQLite file. The backend accesses job data through the database HTTP API, and the frontend accesses data only through the backend.

## Run

```bash
ollama pull qwen2.5:0.5b
ollama serve
docker compose -f student-4/compose.local.yml up --build
```

Open `http://localhost:8404`.

## AI functions

- Grounded job summary
- Structured skill extraction
- Candidate-to-job recommendations

Each AI response includes a timestamped Plan → Act → Observe → Adapt record.

## Test

```bash
python -m unittest discover -s student-4/tests -v
docker compose -f student-4/compose.local.yml config -q
```
