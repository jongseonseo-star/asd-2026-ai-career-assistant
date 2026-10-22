from __future__ import annotations

import os
from typing import Any

import requests
from flask import Flask, redirect, render_template, request, url_for

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:5401").rstrip("/")
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "10"))
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS", "240"))
PORT = int(os.getenv("PORT", "8404"))
app = Flask(__name__)
session = requests.Session()


def api(method: str, path: str, timeout: float = BACKEND_TIMEOUT, **kwargs: Any):
    return session.request(method, f"{BACKEND_API_URL}{path}", timeout=timeout, **kwargs)


def values(resource: str) -> dict[str, Any]:
    data: dict[str, Any] = {key: value.strip() for key, value in request.form.items()}
    if resource == "job_postings":
        data["company_id"] = int(data["company_id"])
        for field in ("salary_min", "salary_max"):
            data[field] = int(data[field]) if data.get(field) else None
    elif resource == "job_skills":
        data["job_posting_id"] = int(data["job_posting_id"])
    return data


def fetch(resource: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    response = api("GET", f"/api/v1/{resource}", params=params)
    response.raise_for_status()
    return response.json()


@app.get("/")
def index():
    notice = request.args.get("notice")
    error = request.args.get("error")
    query = request.args.get("q", "").strip()
    try:
        companies = fetch("companies")
        jobs = fetch("jobs/enriched")
        filtered_jobs = fetch("jobs/enriched", params={"q": query}) if query else jobs
        skills = fetch("job_skills")
    except requests.RequestException:
        companies, jobs, filtered_jobs, skills = [], [], [], []
        error = "The Job Listing API is currently unavailable."
    return render_template(
        "index.html", companies=companies, jobs=jobs, filtered_jobs=filtered_jobs, skills=skills,
        notice=notice, error=error, query=query
    )


@app.get("/ready")
def ready():
    try:
        response = api("GET", "/ready")
        return ({"status": "ready", "service": "student-4-frontend"}, 200) if response.ok else ({"status": "not-ready"}, 503)
    except requests.RequestException:
        return {"status": "not-ready"}, 503


@app.post("/actions/<resource>/create")
def create(resource: str):
    if resource not in {"companies", "job_postings", "job_skills"}:
        return redirect(url_for("index", error="Unknown resource."))
    try:
        response = api("POST", f"/api/v1/{resource}", json=values(resource))
        if not response.ok:
            return redirect(url_for("index", error=response.json().get("error", "Create failed.")))
        return redirect(url_for("index", notice="Record created."))
    except (ValueError, requests.RequestException):
        return redirect(url_for("index", error="Unable to create the record."))


@app.post("/actions/<resource>/<int:item_id>/update")
def update(resource: str, item_id: int):
    if resource not in {"companies", "job_postings", "job_skills"}:
        return redirect(url_for("index", error="Unknown resource."))
    try:
        response = api("PUT", f"/api/v1/{resource}/{item_id}", json=values(resource))
        if not response.ok:
            return redirect(url_for("index", error=response.json().get("error", "Update failed.")))
        return redirect(url_for("index", notice="Record updated."))
    except (ValueError, requests.RequestException):
        return redirect(url_for("index", error="Unable to update the record."))


@app.post("/actions/<resource>/<int:item_id>/delete")
def delete(resource: str, item_id: int):
    if resource not in {"companies", "job_postings", "job_skills"}:
        return redirect(url_for("index", error="Unknown resource."))
    try:
        response = api("DELETE", f"/api/v1/{resource}/{item_id}")
        if not response.ok:
            return redirect(url_for("index", error=response.json().get("error", "Delete failed.")))
        return redirect(url_for("index", notice="Record deleted."))
    except requests.RequestException:
        return redirect(url_for("index", error="Unable to delete the record."))


@app.post("/ai/jobs/<int:job_id>/<action>")
def ai_job(job_id: int, action: str):
    endpoint = {"summary": "summary", "skills": "extract-skills"}.get(action)
    if endpoint is None:
        return render_template("ai_result.html", error="Unknown AI action.")
    try:
        response = api("POST", f"/api/v1/ai/jobs/{job_id}/{endpoint}", timeout=AI_TIMEOUT)
        payload = response.json()
        return render_template("ai_result.html", payload=payload if response.ok else None, error=payload.get("error") if not response.ok else None)
    except requests.RequestException:
        return render_template("ai_result.html", error="Ollama or the backend is unavailable.")


@app.post("/ai/recommendations")
def ai_recommendations():
    profile = request.form.get("candidate_profile", "").strip()
    try:
        response = api("POST", "/api/v1/ai/recommendations", timeout=AI_TIMEOUT, json={"candidate_profile": profile})
        payload = response.json()
        return render_template("ai_result.html", payload=payload if response.ok else None, error=payload.get("error") if not response.ok else None)
    except requests.RequestException:
        return render_template("ai_result.html", error="Ollama or the backend is unavailable.")


@app.post("/mcp/jobs/<int:job_id>/context")
def mcp_context(job_id: int):
    return shared_result(f"/api/v1/mcp/jobs/{job_id}/context", "mcp")


@app.post("/rag/jobs/<int:job_id>/answer")
def rag_answer(job_id: int):
    return shared_result(f"/api/v1/rag/jobs/{job_id}/answer", "rag",
                         {"query": request.form.get("query", "").strip()})


@app.post("/multi-agent/jobs/<int:job_id>/analyse")
def multi_agent_analyse(job_id: int):
    return multi_agent_result(job_id, f"/api/v1/multi-agent/jobs/{job_id}/analyse",
                              {"query": request.form.get("query", "").strip()})


@app.post("/multi-agent/jobs/<int:job_id>/runs/<uuid:run_id>/decision")
def multi_agent_decision(job_id: int, run_id):
    return multi_agent_result(job_id, f"/api/v1/multi-agent/jobs/{job_id}/runs/{run_id}/decision",
                              {key: request.form.get(key, "").strip() for key in ("decision", "reason", "evidence_used")})


def multi_agent_result(job_id: int, path: str, data: dict):
    try:
        response = api("POST", path, timeout=AI_TIMEOUT, json=data)
        payload = response.json()
        return render_template("multi_agent_result.html", job_id=job_id,
                               payload=payload if response.ok else None,
                               error=None if response.ok else payload.get("error", "The request failed."))
    except (requests.RequestException, ValueError):
        return render_template("multi_agent_result.html", job_id=job_id,
                               error="The backend or local Multi-Agent server is unavailable.")


def shared_result(path: str, mode: str, data: dict | None = None):
    try:
        response = api("POST", path, timeout=AI_TIMEOUT, json=data)
        payload = response.json()
        return render_template("shared_result.html", mode=mode,
                               payload=payload if response.ok else None,
                               error=None if response.ok else payload.get("error", "The request failed."))
    except (requests.RequestException, ValueError):
        return render_template("shared_result.html", mode=mode,
                               error="The backend or shared local service is unavailable.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)  # noqa: S104 - Docker forwards the frontend port to this service.
