from __future__ import annotations

import os
from typing import Any

import requests
from flask import Flask, jsonify, make_response, render_template_string, request
from markupsafe import escape
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:5001").rstrip("/")
PORT = int(os.getenv("PORT", "8083"))
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "10"))
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS", "180"))

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
session = requests.Session()


class BackendUnavailable(Exception):
    pass


def backend_request(method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None, timeout: float | None = None) -> tuple[Any, int]:
    try:
        response = session.request(method, f"{BACKEND_API_URL}{path}", json=json_body, params=params, timeout=timeout or BACKEND_TIMEOUT)
    except requests.Timeout as error:
        raise BackendUnavailable("The Student 3 backend request timed out.") from error
    except requests.RequestException as error:
        raise BackendUnavailable("The Student 3 backend is unavailable.") from error

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": "The Student 3 backend returned invalid data."}
    return payload, response.status_code


def fetch_collection(path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload, status = backend_request("GET", path, params=params)
    if status != 200:
        raise BackendUnavailable(str(payload.get("error", "Unable to load data from the backend.")) if isinstance(payload, dict) else "Unable to load data from the backend.")
    if not isinstance(payload, list):
        raise BackendUnavailable("The backend returned an invalid collection.")
    return payload


def response_with_trigger(html: str, trigger_name: str | None = None):
    response = make_response(html, 200)
    if trigger_name:
        response.headers["HX-Trigger"] = trigger_name
    return response


@app.get("/")
def index():
    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Interview Preparation Management</title>
      <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js"></script>
      <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #18212f; }
        .wrap { max-width: 1100px; margin: 0 auto; padding: 2rem; }
        .hero { background: linear-gradient(135deg, #1d4ed8, #7c3aed); color: white; border-radius: 16px; padding: 1.5rem 2rem; margin-bottom: 1rem; }
        .grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 1rem; }
        .panel { background: white; border-radius: 12px; padding: 1rem; box-shadow: 0 8px 24px rgba(0,0,0,.08); }
        form { display: grid; gap: .8rem; }
        input, select, textarea, button { font: inherit; }
        input, select, textarea { width: 100%; box-sizing: border-box; padding: .7rem; border: 1px solid #dfe3ea; border-radius: 8px; }
        button { cursor: pointer; background: #1d4ed8; color: white; border: none; border-radius: 8px; padding: .8rem 1rem; }
        .muted { color: #5f6f86; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border-bottom: 1px solid #edf0f4; padding: .7rem .5rem; text-align: left; }
        .status { padding: .5rem .75rem; border-radius: 999px; display: inline-block; font-size: 0.8rem; }
        .status.ready { background:#dcfce7;color:#166534; }
        .status.error { background:#fee2e2;color:#b91c1c; }
        .card { background: #f9fafb; border: 1px solid #edf0f4; border-radius: 10px; padding: .8rem; margin-top: .8rem; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <h1>Interview Preparation Management</h1>
          <p class="muted" style="color: rgba(255,255,255,.9);">Create interview sessions, generate role-specific questions, and evaluate responses with AI feedback.</p>
          <div id="service-status" hx-get="/ui/status" hx-trigger="load, every 30s" hx-swap="innerHTML"></div>
        </div>

        <div class="grid">
          <section class="panel">
            <h2>Create session</h2>
            <form hx-post="/ui/sessions" hx-target="#sessions-list" hx-swap="innerHTML">
              <input name="candidate_name" placeholder="Candidate name" required>
              <input name="target_role" placeholder="Target role" required>
              <select name="interview_type">
                <option value="technical">Technical</option>
                <option value="behavioral">Behavioral</option>
                <option value="case">Case</option>
                <option value="general">General</option>
              </select>
              <textarea name="notes" placeholder="Session notes"></textarea>
              <button type="submit">Create session</button>
            </form>
          </section>

          <section class="panel">
            <h2>Session workflow</h2>
            <div class="card">
              <strong>1.</strong> Create mock interview session.
            </div>
            <div class="card">
              <strong>2.</strong> Generate job-specific questions from the backend AI prompt.
            </div>
            <div class="card">
              <strong>3.</strong> Submit answers and review scoring + improvement tips.
            </div>
          </section>
        </div>

        <section class="panel" style="margin-top: 1rem;">
          <h2>Interview sessions</h2>
          <div id="sessions-list" hx-get="/ui/sessions" hx-trigger="load, sessionDataChanged from:body" hx-swap="innerHTML"></div>
        </section>
      </div>
    </body>
    </html>
    """, backend_api_url=BACKEND_API_URL)


@app.get("/ui/status")
def ui_status():
    try:
        payload, status = backend_request("GET", "/ready")
        if status == 200 and isinstance(payload, dict) and payload.get("status") == "ready":
            return f'<span class="status ready">Backend ready</span>'
        return f'<span class="status error">Backend unavailable</span>'
    except BackendUnavailable as error:
        return f'<span class="status error">{error}</span>'


@app.get("/ui/sessions")
def ui_sessions():
    try:
        sessions = fetch_collection("/api/v1/interview-sessions")
    except BackendUnavailable as error:
        return f'<div class="card"><strong>Unable to load sessions.</strong><br>{error}</div>'

    if not sessions:
        return '<div class="card">No interview sessions yet.</div>'

    rows = "".join(
        f"""
        <tr>
          <td>{session.get('candidate_name', 'Candidate')}</td>
          <td>{session.get('target_role', 'Role')}</td>
          <td>{session.get('interview_type', 'general')}</td>
          <td>{session.get('status', 'draft')}</td>
          <td>{session.get('overall_score', 0)}</td>
          <td>
            <form hx-post="/ui/questions/generate" hx-target="#session-{session['id']}" hx-swap="innerHTML">
              <input type="hidden" name="session_id" value="{session['id']}">
              <button type="submit">Generate questions</button>
            </form>
          </td>
          <td>
            <button hx-delete="/ui/sessions/{session['id']}" hx-target="#sessions-list" hx-swap="innerHTML">Delete</button>
          </td>
        </tr>
        <tr id="session-{session['id']}"><td colspan="7"><div class='card'>Session detail panel pending.</div></td></tr>
        """ for session in sessions
    )

    return f"""
    <table>
      <thead><tr><th>Candidate</th><th>Role</th><th>Interview type</th><th>Status</th><th>Overall score</th><th>Generate</th><th>Delete</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


@app.post("/ui/sessions")
def ui_create_session():
    body = {
        "candidate_name": request.form.get("candidate_name", "").strip(),
        "target_role": request.form.get("target_role", "").strip(),
        "interview_type": request.form.get("interview_type", "general").strip(),
        "status": "draft",
        "notes": request.form.get("notes", "").strip(),
    }
    try:
        payload, status = backend_request("POST", "/api/v1/interview-sessions", json_body=body)
    except BackendUnavailable as error:
        return response_with_trigger(f'<div class="card">{error}</div>', "sessionDataChanged")

    if status != 201:
        message = payload.get("error", "Unable to create session.") if isinstance(payload, dict) else "Unable to create session."
        return response_with_trigger(f'<div class="card">{message}</div>', "sessionDataChanged")

    return response_with_trigger("", "sessionDataChanged")


@app.delete("/ui/sessions/<int:session_id>")
def ui_delete_session(session_id: int):
    try:
        payload, status = backend_request("DELETE", f"/api/v1/interview-sessions/{session_id}")
    except BackendUnavailable as error:
        return response_with_trigger(f'<div class="card">{error}</div>', "sessionDataChanged")
    if status != 200:
        message = payload.get("error", "Unable to delete session.") if isinstance(payload, dict) else "Unable to delete session."
        return response_with_trigger(f'<div class="card">{message}</div>', "sessionDataChanged")
    return response_with_trigger("", "sessionDataChanged")


@app.post("/ui/questions/generate")
def ui_generate_questions():
    session_id = request.form.get("session_id")
    if not session_id:
        return '<div class="card">Missing interview session id.</div>'
    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-sessions/{int(session_id)}/generate-questions",
            json_body={"question_count": 3},
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'
    if status != 200:
        message = payload.get("error", "Questions could not be generated.") if isinstance(payload, dict) else "Questions could not be generated."
        return f'<div class="card">{message}</div>'

    questions = payload.get("generated_questions", [])
    rows = "".join(
        f"""
        <div class="card">
          <strong>Q{idx + 1}.</strong> {q.get('question_text', q.get('question', 'Question'))}
          <form hx-post="/ui/questions/{q['id']}/evaluate" hx-target="#response-{q['id']}" hx-swap="innerHTML" style="margin-top:.6rem;">
            <textarea name="answer" placeholder="Type your answer here" required></textarea>
            <button type="submit">Evaluate answer</button>
          </form>
          <div id="response-{q['id']}"></div>
        </div>
        """ for idx, q in enumerate(questions)
    )
    return f'<div class="card"><strong>Generated questions</strong>{rows}</div>'


@app.post("/ui/questions/<int:question_id>/evaluate")
def ui_evaluate_answer(question_id: int):
    answer = request.form.get("answer", "").strip()
    if not answer:
        return '<div class="card">Please provide an answer before evaluating.</div>'
    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-questions/{question_id}/evaluate-answer",
            json_body={"answer": answer},
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'
    if status != 200:
        message = payload.get("error", "The answer could not be evaluated.") if isinstance(payload, dict) else "The answer could not be evaluated."
        return f'<div class="card">{message}</div>'

    score = payload.get("score", 0)
    feedback = payload.get("feedback", "No feedback returned.")
    tips = payload.get("improvement_tips", "Keep practising.")
    return f"""
    <div class="card">
      <strong>Score:</strong> {score}<br>
      <strong>Feedback:</strong> {feedback}<br>
      <strong>Improvement tips:</strong> {tips}
    </div>
    """


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "student-3-frontend"}), 200


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Frontend route not found."}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
