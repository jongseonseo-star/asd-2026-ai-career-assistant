#!/usr/bin/env bash
# Run from a normal local terminal. Does not request elevated privileges.
set -euo pipefail

DEMO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEMO_ROOT"

if [[ "${1:-}" == "--help" ]]; then
  cat <<'HELP'
Usage: bash scripts/start_student2_demo.sh
Creates/checks this checkout's Python 3.12 .venv, installs runtime dependencies,
then starts the local Student 2 demo supervisor. Run in your normal terminal.
Keep the terminal open. Ctrl+C stops only the three AI processes it starts;
Docker containers and database volumes remain in place.
HELP
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "Unsupported argument. Use --help." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is unavailable. Start Docker Desktop and check its CLI installation." >&2
  exit 1
fi
if ! docker info --format '{{.ServerVersion}}'; then
  echo "Docker cannot be reached. Run this command yourself in your normal VS Code terminal with Docker Desktop running." >&2
  exit 1
fi

DEMO_PYTHON="$(command -v python3.12 || true)"
if [[ -z "$DEMO_PYTHON" && -x /opt/homebrew/bin/python3.12 ]]; then
  DEMO_PYTHON=/opt/homebrew/bin/python3.12
fi
if [[ -z "$DEMO_PYTHON" ]]; then
  echo "Python 3.12 was not found. Install/select Python 3.12 before continuing." >&2
  exit 1
fi
if [[ ! -e .venv ]]; then
  "$DEMO_PYTHON" -m venv .venv
fi
if ! .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12)'; then
  echo "The existing .venv is not a working Python 3.12 environment. It has not been overwritten." >&2
  exit 1
fi

mkdir -p reports/demo-bootstrap
echo "Checking/installing runtime dependencies (first run may take several minutes)..."
.venv/bin/python -m pip install --disable-pip-version-check \
  --cache-dir "$DEMO_ROOT/reports/demo-pip-cache" \
  -r ai-services/requirements.txt -r student-2/backend/requirements.txt \
  2>&1 | tee reports/demo-bootstrap/dependencies.log
.venv/bin/python -B -c 'import flask, fastmcp, chromadb, yaml, requests; print("Runtime imports OK")'

exec .venv/bin/python -B -u scripts/start_student2_demo.py
