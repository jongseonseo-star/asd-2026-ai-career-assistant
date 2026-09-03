from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request

DATABASE_API_URL = os.getenv("DATABASE_API_URL", "http://127.0.0.1:5402").rstrip("/")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
DATABASE_TIMEOUT = float(os.getenv("DATABASE_TIMEOUT_SECONDS", "5"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
PORT = int(os.getenv("PORT", "5401"))
PROMPTS = Path(__file__).parent / "prompts"

app = Flask(__name__)
session = requests.Session()


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 503, dependency: str | None = None):
        self.message, self.status, self.dependency = message, status, dependency


@app.errorhandler(ServiceError)
def service_error(error: ServiceError):
    payload = {"error": error.message}
    if error.dependency:
        payload["dependency"] = error.dependency
    return jsonify(payload), error.status


def db_request(method: str, path: str, **kwargs: Any) -> requests.Response:
    try:
        response = session.request(method, f"{DATABASE_API_URL}{path}", timeout=DATABASE_TIMEOUT, **kwargs)
    except requests.RequestException as error:
        raise ServiceError("Database API is unavailable.", 503, "student-4-database") from error
    return response


def proxy(method: str, path: str):
    response = db_request(method, path, params=request.args, json=request.get_json(silent=True))
    if response.status_code == 204:
        return "", 204
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": "Database API returned an invalid response."}
    return jsonify(payload), response.status_code


def prompt(name: str) -> str:
    try:
        return (PROMPTS / name).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ServiceError(f"Prompt asset {name} is unavailable.", 500, "prompt-assets") from error


def ollama_generate(task: str, context: Any) -> str:
    user_prompt = f"{task}\n\nCONTEXT:\n{json.dumps(context, indent=2)}"
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": prompt("system_prompt.txt")},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.2},
        }
        if "Return JSON only" in task:
            payload["format"] = "json"
        response = session.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        raise ServiceError("Ollama could not generate a response.", 503, "ollama") from error


def all_records(resource: str) -> list[dict[str, Any]]:
    response = db_request("GET", f"/api/v1/{resource}")
    if response.status_code != 200:
        raise ServiceError("Unable to retrieve job data.", response.status_code, "student-4-database")
    value = response.json()
    if not isinstance(value, list):
        raise ServiceError("Database API returned invalid job data.", 502, "student-4-database")
    return value


def job_context(job_id: int) -> dict[str, Any]:
    job_response = db_request("GET", f"/api/v1/job_postings/{job_id}")
    if job_response.status_code != 200:
        raise ServiceError("Job posting not found.", job_response.status_code)
    job = job_response.json()
    companies = {row["id"]: row for row in all_records("companies")}
    skills = [row for row in all_records("job_skills") if row["job_posting_id"] == job_id]
    return {"job": job, "company": companies.get(job["company_id"]), "skills": skills}


def agentic_result(goal: str, action: str, observation: str, adaptation: str, result: Any):
    return {
        "workflow": {
            "plan": goal,
            "act": action,
            "observe": observation,
            "adapt": adaptation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "result": result,
        "model": OLLAMA_MODEL,
    }


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "student-4-backend"})


@app.get("/ready")
def ready():
    response = db_request("GET", "/health")
    if response.status_code != 200:
        raise ServiceError("Database API is not ready.", 503, "student-4-database")
    return jsonify({"status": "ready", "service": "student-4-backend"})


@app.route("/api/v1/<resource>", methods=["GET", "POST"])
def resource_collection(resource: str):
    if resource not in {"companies", "job_postings", "job_skills", "stats"}:
        return jsonify({"error": "Resource not found."}), 404
    return proxy(request.method, f"/api/v1/{resource}")


@app.route("/api/v1/<resource>/<int:item_id>", methods=["GET", "PUT", "DELETE"])
def resource_item(resource: str, item_id: int):
    if resource not in {"companies", "job_postings", "job_skills"}:
        return jsonify({"error": "Resource not found."}), 404
    return proxy(request.method, f"/api/v1/{resource}/{item_id}")


@app.get("/api/v1/jobs/enriched")
def enriched_jobs():
    jobs = all_records("job_postings")
    companies = {row["id"]: row for row in all_records("companies")}
    skills = all_records("job_skills")
    result = []
    for job in jobs:
        item = dict(job)
        item["company"] = companies.get(job["company_id"])
        item["skills"] = [skill for skill in skills if skill["job_posting_id"] == job["id"]]
        result.append(item)
    query = request.args.get("q", "").strip().lower()
    if query:
        result = [row for row in result if query in json.dumps(row).lower()]
    return jsonify(result)


@app.get("/api/v1/ai/status")
def ai_status():
    try:
        response = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        response.raise_for_status()
        return jsonify({"status": "available", "model": OLLAMA_MODEL, "runtime": "Ollama"})
    except requests.RequestException:
        return jsonify({"status": "unavailable", "model": OLLAMA_MODEL, "runtime": "Ollama"}), 503


@app.post("/api/v1/ai/jobs/<int:job_id>/summary")
def summarise(job_id: int):
    context = job_context(job_id)
    result = ollama_generate(prompt("job_summary.txt"), context)
    return jsonify(agentic_result(
        "Create a grounded candidate-friendly job summary.",
        "Retrieve the job, company and skills, then ask Ollama to summarise them.",
        "A summary was generated from the owned database context.",
        "Constrain the response to the supplied evidence and expose it to the frontend.", result
    ))


@app.post("/api/v1/ai/jobs/<int:job_id>/extract-skills")
def extract_skills(job_id: int):
    context = job_context(job_id)
    raw = ollama_generate(prompt("skill_extraction.txt"), context)
    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ServiceError("The model returned invalid skill JSON.", 502, "ollama") from error
    return jsonify(agentic_result(
        "Identify job skills supported by the posting.",
        "Retrieve controlled job context and request structured extraction from Ollama.",
        f"The model returned {len(extracted.get('skills', []))} skill candidates.",
        "Validate the JSON before presenting skills for human review.", extracted
    ))


@app.post("/api/v1/ai/recommendations")
def recommendations():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("candidate_profile"), str) or not data["candidate_profile"].strip():
        return jsonify({"error": "candidate_profile is required."}), 400
    jobs = enriched_jobs()[0].get_json()
    context = {"candidate_profile": data["candidate_profile"].strip()[:4000], "jobs": jobs}
    result = ollama_generate(prompt("job_recommendation.txt"), context)
    return jsonify(agentic_result(
        "Recommend suitable jobs without overstating fit.",
        "Compare candidate-supplied context against current job records using Ollama.",
        f"Compared the candidate against {len(jobs)} available jobs.",
        "Return ranked options with both match evidence and skill gaps.", result
    ))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
