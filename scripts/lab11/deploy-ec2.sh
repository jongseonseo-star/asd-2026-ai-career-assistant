#!/usr/bin/env bash
set -euo pipefail

# Keep image builds within the small EC2 instance's memory limit.
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

if [[ ! -f .env.cloud ]]; then
    cp .env.cloud.example .env.cloud
fi

docker compose --env-file .env.cloud -f docker-compose.cloud.yml config --quiet
trap 'docker compose --env-file .env.cloud -f docker-compose.cloud.yml logs --no-color --tail=100 || true' ERR

docker compose --env-file .env.cloud -f docker-compose.cloud.yml \
    up -d --build --wait --wait-timeout 180

# Check the public frontend routes and the private backend/database connections.
docker compose --env-file .env.cloud -f docker-compose.cloud.yml \
    exec -T student-4-backend python - <<'PY'
import requests

for path in ("/", "/resume/", "/interviews/", "/jobs/"):
    response = requests.get(
        f"http://shared-frontend{path}", timeout=10, allow_redirects=False
    )
    assert response.status_code == (200 if path == "/" else 302), path
    print(f"Frontend {path}: OK")

for url, error_text in (
    ("http://shared-frontend:8082/ui/profiles", "feature-card--error"),
    ("http://shared-frontend:8303/ui/sessions", "Unable to load sessions."),
    ("http://shared-frontend:8404/", "The Job Listing API is currently unavailable."),
):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    assert error_text not in response.text, f"Frontend could not load data: {url}"
    print(f"Frontend data {url}: OK")

for base_url, resource in (
    ("http://student-2-backend:5001", "profiles"),
    ("http://student-3-backend:5001", "interview-sessions"),
    ("http://student-4-backend:5401", "job_postings"),
):
    response = requests.get(f"{base_url}/ready", timeout=10)
    response.raise_for_status()
    assert response.json()["status"] == "ready"

    response = requests.get(f"{base_url}/api/v1/{resource}", timeout=10)
    response.raise_for_status()
    assert isinstance(response.json(), list), f"Invalid collection: {resource}"
    print(f"Backend and database {resource}: OK")
PY

echo "Cloud deployment checks passed."
