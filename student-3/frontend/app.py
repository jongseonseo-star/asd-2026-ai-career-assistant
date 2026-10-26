from __future__ import annotations

import json
import os
from typing import Any

import requests
from flask import Flask, jsonify, make_response, render_template_string, request
from markupsafe import escape
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:5001").rstrip("/")
PORT = int(os.getenv("PORT", "8083"))
HOST = os.getenv("HOST", "127.0.0.1")
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "10"))
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS", "180"))
STATUS_TIMEOUT = float(os.getenv("STATUS_TIMEOUT_SECONDS", "5"))

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


def status_badge(label: str, state: str, detail: str) -> str:
    safe_state = escape(state)
    safe_detail = escape(detail)
    return f'<div class="dependency-status"><span class="status-dot {safe_state}"></span><div><strong>{escape(label)}</strong><span class="status-detail">{safe_detail}</span></div></div>'


def dependency_status() -> str:
    backend_state = "error"
    backend_detail = "Unavailable"
    database_state = "unknown"
    database_detail = "Unknown"
    ollama_state = "error"
    ollama_detail = "Unavailable"
    mcp_state = "warning"
    mcp_detail = "Disabled"
    rag_state = "warning"
    rag_detail = "Disabled"
    multi_agent_state = "warning"
    multi_agent_detail = "Disabled"

    try:
        backend_payload, backend_http_status = backend_request("GET", "/health", timeout=STATUS_TIMEOUT)
        if backend_http_status == 200 and isinstance(backend_payload, dict) and backend_payload.get("status") == "healthy":
            backend_state, backend_detail = "ready", "Connected"
        else:
            backend_detail = "Not healthy"

        readiness_payload, readiness_http_status = backend_request("GET", "/ready", timeout=STATUS_TIMEOUT)
        database_payload = readiness_payload.get("dependencies", {}).get("database", {}) if isinstance(readiness_payload, dict) else {}
        if readiness_http_status == 200 and isinstance(database_payload, dict) and database_payload.get("status") == "healthy":
            database_state, database_detail = "ready", "Connected"
        else:
            database_state, database_detail = "error", "Unavailable"
    except BackendUnavailable as error:
        backend_detail = str(error)

    try:
        ollama_payload, ollama_http_status = backend_request("GET", "/api/v1/ai/status", timeout=STATUS_TIMEOUT)
        if ollama_http_status == 200 and isinstance(ollama_payload, dict) and ollama_payload.get("status") == "available":
            if ollama_payload.get("configured_model_available"):
                ollama_state, ollama_detail = "ready", f"Connected ({ollama_payload.get('configured_model', 'model')})"
            else:
                ollama_state, ollama_detail = "warning", "Connected, model unavailable"
        else:
            ollama_detail = "Not available"
        if isinstance(ollama_payload, dict) and ollama_payload.get("shared_ai_services_enabled"):
            mcp_state, mcp_detail = "ready", "Enabled"
            rag_state, rag_detail = "ready", "Enabled"
            ma_dep = ollama_payload.get("dependencies", {}).get("multi_agent", {})
            if isinstance(ma_dep, dict) and ma_dep.get("status") == "available":
                multi_agent_state, multi_agent_detail = "ready", "Connected"
            else:
                multi_agent_state, multi_agent_detail = "warning", "Ready on host :8767"
    except BackendUnavailable as error:
        ollama_detail = str(error)

    return "".join([
        status_badge("Database", database_state, database_detail),
        status_badge("Backend", backend_state, backend_detail),
        status_badge("Ollama", ollama_state, ollama_detail),
        status_badge("MCP", mcp_state, mcp_detail),
        status_badge("RAG", rag_state, rag_detail),
        status_badge("Multi-Agent", multi_agent_state, multi_agent_detail),
    ])


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
        .status.warning { background:#fef3c7;color:#92400e; }
        .status.error { background:#fee2e2;color:#b91c1c; }
        .status-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:.6rem; margin-top:1rem; }
        .dependency-status { display:flex; align-items:center; gap:.55rem; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.2); border-radius:8px; padding:.65rem .75rem; }
        .dependency-status strong, .status-detail { display:block; }
        .status-detail { color:rgba(255,255,255,.8); font-size:.78rem; margin-top:.15rem; }
        .status-dot { width:.6rem; height:.6rem; flex:0 0 .6rem; border-radius:50%; background:#fca5a5; }
        .status-dot.ready { background:#86efac; }
        .status-dot.warning { background:#fcd34d; }
        @media (max-width: 700px) { .status-grid { grid-template-columns:1fr; } }
        .card { background: #f9fafb; border: 1px solid #edf0f4; border-radius: 10px; padding: .8rem; margin-top: .8rem; }
        /* HTMX Loading States */
        .htmx-indicator { display: none; }
        .htmx-request.htmx-indicator,
        .htmx-request .htmx-indicator { display: flex; }
        .loading-indicator {
          align-items: center;
          gap: 0.6rem;
          margin-top: 0.6rem;
          padding: 0.6rem 0.9rem;
          background: #eff6ff;
          border: 1px solid #bfdbfe;
          border-radius: 8px;
          color: #1e40af;
          font-size: 0.85rem;
          box-shadow: 0 1px 3px rgba(0,0,0,0.05);
          animation: pulse-bg 2s infinite ease-in-out;
        }
        .spinner {
          width: 16px;
          height: 16px;
          border: 2px solid #bfdbfe;
          border-top: 2px solid #1d4ed8;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          flex-shrink: 0;
        }
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes pulse-bg {
          0%, 100% { background: #eff6ff; }
          50% { background: #dbeafe; }
        }
        button:disabled, button[disabled], .htmx-request button[type="submit"] {
          opacity: 0.65;
          cursor: not-allowed;
        }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <h1>Interview Preparation Management</h1>
          <p class="muted" style="color: rgba(255,255,255,.9);">Create interview sessions, generate role-specific questions, and evaluate responses with AI feedback.</p>
                    <div id="service-status" class="status-grid" hx-get="/ui/status" hx-trigger="load, every 30s" hx-swap="innerHTML">
                        <div class="dependency-status"><span class="status-dot loading"></span><div><strong>Database</strong><span class="status-detail">Checking...</span></div></div>
                        <div class="dependency-status"><span class="status-dot loading"></span><div><strong>Backend</strong><span class="status-detail">Checking...</span></div></div>
                        <div class="dependency-status"><span class="status-dot loading"></span><div><strong>Ollama</strong><span class="status-detail">Checking...</span></div></div>
                    </div>
        </div>

        <div class="grid">
          <section class="panel">
            <h2>Create session</h2>
            <form hx-post="/ui/sessions" hx-target="#sessions-list" hx-swap="innerHTML" hx-indicator="#loading-create-session" hx-disabled-elt="find button">
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
              <div id="loading-create-session" class="htmx-indicator loading-indicator">
                <span class="spinner"></span>
                <span>Creating interview session...</span>
              </div>
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
    return dependency_status()


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
            <form hx-post="/ui/questions/generate" hx-target="#session-{session['id']}" hx-swap="innerHTML" hx-indicator="#loading-gen-{session['id']}, #loading-gen-row-{session['id']}" hx-disabled-elt="find button">
              <input type="hidden" name="session_id" value="{session['id']}">
              <select name="mode" aria-label="Question generation mode">
                <option value="multi-agent">Multi-Agent (Release 2)</option>
                <option value="multi-agent-loop15">Multi-Agent (15 Iterations → Human Review)</option>
                <option value="mcp-rag">MCP + RAG</option>
                <option value="mcp">MCP only</option>
                <option value="ai">AI Mode</option>
              </select>
              <button type="submit">Generate questions</button>
              <div id="loading-gen-{session['id']}" class="htmx-indicator loading-indicator" style="margin-top:.4rem; font-size:0.78rem; padding: 0.4rem 0.6rem;">
                <span class="spinner"></span> <span>Generating...</span>
              </div>
            </form>
          </td>
          <td>
            <button hx-delete="/ui/sessions/{session['id']}" hx-target="#sessions-list" hx-swap="innerHTML">Delete</button>
          </td>
        </tr>
        <tr id="session-{session['id']}">
          <td colspan="7">
            <div id="loading-gen-row-{session['id']}" class="htmx-indicator loading-indicator" style="padding: 1rem; margin: 0.5rem 0;">
              <span class="spinner"></span>
              <div>
                <strong>Coordinating Multi-Agent Preparation...</strong>
                <div style="font-size: 0.8rem; color: #475569; margin-top: 3px;">
                  Planner is designing blueprint &bull; Worker is synthesizing questions &bull; Reviewer is auditing quality. Please wait...
                </div>
              </div>
            </div>
            <div class='card'>Session detail panel pending.</div>
          </td>
        </tr>
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
    chosen_mode = request.form.get("mode", "multi-agent")
    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-sessions/{int(session_id)}/generate-questions",
            json_body={"question_count": 3, "mode": chosen_mode},
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'
    if status != 200:
        message = payload.get("error", "Questions could not be generated.") if isinstance(payload, dict) else "Questions could not be generated."
        return f'<div class="card">{message}</div>'

    if payload.get("status") == "context-only":
        return f'<div class="card"><strong>MCP context</strong><br>{escape(payload.get("feedback", "Context retrieved."))}<pre>{escape(str(payload.get("mcp_result", {})))}</pre></div>'

    questions = payload.get("generated_questions") or payload.get("questions") or []

    if payload.get("status") == "pending_human_review":
        run_id = payload.get("run_id", "")
        review = payload.get("review") or {}
        iterations = payload.get("iterations", 15)
        critique = review.get("critique", "Quality audit threshold not met after maximum iterations.")
        score = review.get("score", 70)
        proposed_items = "".join(
            f"""
            <li style="margin-bottom: 0.5rem;">
              <strong>Q{idx + 1}.</strong> {escape(str(q.get('question_text', q.get('question', 'Question'))))}
              {f'<br><small style="color:#64748b;">Category: {escape(str(q.get("category", "General")))}</small>' if q.get("category") else ''}
            </li>
            """ for idx, q in enumerate(questions)
        )
        questions_json_str = json.dumps(questions)

        return f"""
        <div class="card" style="border: 2px solid #f59e0b; background: #fffbeb; margin-top: .8rem;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:#b45309; font-size:1.05rem;">⚠️ Human Review Required (15 Iterations Complete)</strong>
            <span style="background:#d97706; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem; font-weight:bold;">
              Iterations: {iterations} | NEEDS REVISION
            </span>
          </div>
          <div style="margin-top: 0.6rem; font-size: 0.9rem; color: #78350f;">
            The Multi-Agent coordinator reached the maximum limit of {iterations} iterations between Planner and Worker.
            Reviewer scored this {score}/100 with critique: <em>"{escape(str(critique))}"</em>.
            Human review is now required before these questions can be approved and added to the session.
          </div>
          <div style="background:white; border: 1px solid #fed7aa; border-radius:6px; padding:0.8rem; margin: 0.8rem 0;">
            <strong style="color:#9a3412;">Proposed Questions ({len(questions)}):</strong>
            <ol style="margin: 0.4rem 0 0.4rem 1.2rem; padding: 0;">
              {proposed_items}
            </ol>
          </div>
          <form hx-post="/ui/sessions/{session_id}/human-review" hx-target="#session-{session_id}" hx-swap="innerHTML" style="margin-top: 0.8rem;">
            <input type="hidden" name="session_id" value="{session_id}">
            <input type="hidden" name="run_id" value="{escape(str(run_id))}">
            <input type="hidden" name="questions_json" value="{escape(questions_json_str)}">
            <div style="display:flex; gap: 1rem; flex-wrap:wrap; margin-bottom: 0.6rem;">
              <div style="flex:1; min-width:180px;">
                <label style="font-weight:bold; font-size:0.85rem; display:block; margin-bottom:2px;">Reviewer:</label>
                <input type="text" name="reviewer" value="User" style="width:100%; padding: 5px 8px;">
              </div>
              <div style="flex:1; min-width:180px;">
                <label style="font-weight:bold; font-size:0.85rem; display:block; margin-bottom:2px;">Human Decision:</label>
                <select name="decision" style="width:100%; padding: 5px 8px;">
                  <option value="Accept">Accept (Approve all proposed questions)</option>
                  <option value="Partially Accept">Partially Accept</option>
                  <option value="Reject">Reject (Discard proposed questions)</option>
                </select>
              </div>
            </div>
            <div style="margin-bottom: 0.6rem;">
              <label style="font-weight:bold; font-size:0.85rem; display:block; margin-bottom:2px;">Review Rationale / Notes:</label>
              <textarea name="rationale" placeholder="Explain your decision..." style="width:100%; min-height:50px;">Approved after 15 iterations of multi-agent review.</textarea>
            </div>
            <button type="submit" style="background:#d97706; color:white; font-weight:bold; padding: 7px 16px; border:none; border-radius:4px; cursor:pointer;">
              Submit Human Review Decision
            </button>
          </form>
        </div>
        """

    rows = render_question_cards(questions)

    if payload.get("mode") in {"multi-agent", "multi-agent-loop15"}:
        plan = payload.get("plan") or {}
        review = payload.get("review") or {}
        competency_items = []
        for c in plan.get("competencies", []):
            if isinstance(c, dict):
                name = c.get("name") or c.get("title") or c.get("competency")
                desc = c.get("description") or c.get("desc")
                if name and desc:
                    competency_items.append(f'<span title="{escape(str(desc))}">{escape(str(name))}</span>')
                elif name:
                    competency_items.append(escape(str(name)))
                else:
                    competency_items.append(escape(str(c)))
            else:
                competency_items.append(escape(str(c)))
        competencies = ", ".join(competency_items) or "Role-relevant competencies"
        meta_panel = f"""
        <div class="card" style="background:#eff6ff; border: 1px solid #bfdbfe; margin-bottom: 0.8rem;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>Release 2 Multi-Agent Coordinated Preparation</strong>
            <span style="background:#2563eb; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem;">
              Iterations: {payload.get('iterations', 1)} | {escape(str(review.get('verdict', 'approved')).upper())}
            </span>
          </div>
          <div style="margin-top: 0.5rem; font-size: 0.9rem;">
            <strong>Planner Blueprint:</strong> {competencies}<br>
            <strong>Reviewer Quality Audit ({review.get('score', 85)}/100):</strong> {escape(str(review.get('critique', 'Approved')))}
          </div>
        </div>
        """
        return f'<div class="card">{meta_panel}{rows}</div>'

    sources = ", ".join(str(source) for source in payload.get("sources", [])) or "No sources returned"
    return f'<div class="card"><strong>Generated questions</strong><br><small>Grounding confidence: {escape(payload.get("confidence", "unknown"))} | Sources: {escape(sources)}</small>{rows}</div>'


def render_question_cards(questions: list[dict[str, Any]]) -> str:
    return "".join(
        f"""
        <div class="card" style="margin-top: .8rem; border-left: 3px solid #2563eb;">
          <strong>Q{idx + 1}.</strong> {escape(str(q.get('question_text', q.get('question', 'Question'))))}
          {f'<br><small style="color:#64748b;">Category: {escape(str(q.get("category", "General")))}</small>' if q.get("category") else ''}
          <form hx-post="/ui/questions/{q['id']}/evaluate" hx-target="#response-{q['id']}" hx-swap="innerHTML" hx-indicator="#loading-eval-{q['id']}" hx-disabled-elt="find button" style="margin-top:.6rem;">
            <textarea name="answer" placeholder="Type your answer here" required></textarea>
            <div style="display:flex; gap:.5rem; align-items:center; margin-top:.4rem; flex-wrap:wrap;">
              <select name="mode" aria-label="Answer evaluation mode" style="width:auto; flex:1; min-width:180px;">
                <option value="multi-agent">Multi-Agent (Release 2)</option>
                <option value="multi-agent-loop15">Multi-Agent (15 Iterations → Human Review)</option>
                <option value="mcp-rag">MCP + RAG</option>
                <option value="mcp">MCP only</option>
                <option value="ai">AI Mode</option>
              </select>
              <button type="submit" style="white-space:nowrap;">Evaluate answer</button>
            </div>
            <div id="loading-eval-{q['id']}" class="htmx-indicator loading-indicator">
              <span class="spinner"></span>
              <div>
                <strong>Evaluating answer...</strong>
                <div style="font-size:0.8rem; color:#475569; margin-top:2px;">
                  Coordinating Multi-Agent evaluation (Worker scoring &amp; Reviewer quality audit). Please wait...
                </div>
              </div>
            </div>
          </form>
          <div id="response-{q['id']}"></div>
        </div>
        """ for idx, q in enumerate(questions)
    )


@app.post("/ui/sessions/<int:session_id>/human-review")
def ui_session_human_review(session_id: int):
    decision = request.form.get("decision", "Accept")
    reviewer = request.form.get("reviewer", "User").strip() or "User"
    rationale = request.form.get("rationale", "").strip()
    run_id = request.form.get("run_id", "").strip()
    questions_raw = request.form.get("questions_json", "[]")
    try:
        questions = json.loads(questions_raw)
    except Exception:
        questions = []

    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-sessions/{session_id}/human-review",
            json_body={
                "run_id": run_id,
                "decision": decision,
                "reviewer": reviewer,
                "rationale": rationale,
                "questions": questions,
            },
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'

    if status != 200:
        message = payload.get("error", "Human review could not be recorded.") if isinstance(payload, dict) else "Human review failed."
        return f'<div class="card">{message}</div>'

    if decision == "Reject":
        return f"""
        <div class="card" style="border-left: 4px solid #ef4444; background:#fef2f2; margin-top: .8rem;">
          <strong style="color:#b91c1c;">❌ Human Review: Rejected</strong>
          <p style="margin: 0.4rem 0 0 0; font-size: 0.9rem;">
            Decision recorded by <strong>{escape(reviewer)}</strong>: {escape(rationale or 'Proposed questions discarded.')}.
            No questions were added to this interview session.
          </p>
        </div>
        """

    saved_questions = payload.get("questions", [])
    rows = render_question_cards(saved_questions)
    decision_banner = f"""
    <div class="card" style="background:#ecfdf5; border: 1px solid #a7f3d0; border-left: 4px solid #059669; margin-bottom: 0.8rem;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <strong style="color:#065f46;">✅ Human Review Completed ({escape(decision)})</strong>
        <span style="background:#059669; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem; font-weight:bold;">
          Reviewer: {escape(reviewer)}
        </span>
      </div>
      <div style="margin-top: 0.4rem; font-size: 0.9rem; color:#064e3b;">
        <strong>Reviewer Rationale:</strong> {escape(rationale or 'Questions approved after review.')}<br>
        Questions have been persisted and are ready for candidate practice below.
      </div>
    </div>
    """
    return f'<div class="card">{decision_banner}{rows}</div>'


def format_assessment_content(raw_feedback: Any, default_tips: Any = None) -> tuple[str, str]:
    fb = raw_feedback
    extracted_tips = default_tips

    if isinstance(fb, str):
        trimmed = fb.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                fb = json.loads(trimmed)
            except Exception:
                try:
                    import ast
                    fb = ast.literal_eval(trimmed)
                except Exception:
                    fb = raw_feedback

    if isinstance(fb, dict):
        parts = []
        summary = fb.get("summary") or fb.get("assessment") or fb.get("feedback")
        if summary and isinstance(summary, str):
            parts.append(f"<p style='margin: 0.3rem 0;'>{escape(summary)}</p>")

        strengths = fb.get("strengths")
        if isinstance(strengths, list) and strengths:
            items = "".join(f"<li>{escape(str(s))}</li>" for s in strengths if str(s).strip())
            if items:
                parts.append(f"<div style='margin-top:0.4rem;'><strong>Strengths:</strong><ul style='margin:0.2rem 0 0.4rem 1.2rem; padding:0;'>{items}</ul></div>")

        gaps = fb.get("gaps")
        if isinstance(gaps, list) and gaps:
            items = "".join(f"<li>{escape(str(g))}</li>" for g in gaps if str(g).strip())
            if items:
                parts.append(f"<div style='margin-top:0.4rem;'><strong>Areas for Improvement:</strong><ul style='margin:0.2rem 0 0.4rem 1.2rem; padding:0;'>{items}</ul></div>")

        tips_in_fb = fb.get("improvement_tips")
        if tips_in_fb and (not extracted_tips or extracted_tips in {"Keep practising.", "Continue practicing structured communication."}):
            if isinstance(tips_in_fb, list):
                extracted_tips = "; ".join(str(t).strip() for t in tips_in_fb if str(t).strip())
            else:
                extracted_tips = str(tips_in_fb).strip()

        formatted_fb = "".join(parts) if parts else escape(str(raw_feedback))
    else:
        formatted_fb = escape(str(raw_feedback))

    if isinstance(extracted_tips, list):
        formatted_tips = "; ".join(str(t).strip() for t in extracted_tips if str(t).strip())
    else:
        formatted_tips = str(extracted_tips or "Keep practising.").strip()

    return formatted_fb, formatted_tips


@app.post("/ui/questions/<int:question_id>/evaluate")
def ui_evaluate_answer(question_id: int):
    answer = request.form.get("answer", "").strip()
    if not answer:
        return '<div class="card">Please provide an answer before evaluating.</div>'
    chosen_mode = request.form.get("mode", "multi-agent")
    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-questions/{question_id}/evaluate-answer",
            json_body={"answer": answer, "mode": chosen_mode},
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'
    if status != 200:
        message = payload.get("error", "The answer could not be evaluated.") if isinstance(payload, dict) else "The answer could not be evaluated."
        return f'<div class="card">{message}</div>'

    if payload.get("status") == "context-only":
        return f'<div class="card"><strong>MCP context</strong><br>{escape(payload.get("feedback", "Context retrieved."))}<pre>{escape(str(payload.get("mcp_result", {})))}</pre></div>'

    score = payload.get("score", 0)
    raw_feedback = payload.get("feedback", "No feedback returned.")
    raw_tips = payload.get("improvement_tips", "Keep practising.")
    formatted_fb, formatted_tips = format_assessment_content(raw_feedback, raw_tips)

    if payload.get("status") == "pending_human_review":
        run_id = payload.get("run_id", "")
        review = payload.get("review") or {}
        iterations = payload.get("iterations", 15)
        critique = review.get("critique", "Quality audit threshold not met after maximum iterations.")
        raw_feedback_str = str(raw_feedback) if not isinstance(raw_feedback, (dict, list)) else json.dumps(raw_feedback)
        raw_tips_str = str(raw_tips) if not isinstance(raw_tips, list) else "; ".join(str(t) for t in raw_tips)

        return f"""
        <div class="card" style="border: 2px solid #f59e0b; background: #fffbeb; margin-top: .6rem;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:#b45309;">⚠️ Human Review Required (15 Iterations Complete)</strong>
            <span style="background:#d97706; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem; font-weight:bold;">
              Iterations: {iterations} | NEEDS REVISION
            </span>
          </div>
          <div style="margin-top: 0.5rem; font-size: 0.9rem; color: #78350f;">
            Multi-agent answer evaluation reached the maximum of {iterations} iterations.
            Reviewer scored worker output {review.get('score', 75)}/100 with critique: <em>"{escape(str(critique))}"</em>.
            Human review is now required.
          </div>
          <div style="background:white; border: 1px solid #fed7aa; border-radius: 6px; padding: .6rem; margin: .6rem 0; font-size: 0.9rem;">
            <strong>Worker Proposed Score:</strong> {score}/100<br>
            <strong>Worker Proposed Feedback:</strong> {formatted_fb}<br>
            <strong>Worker Proposed Tips:</strong> {escape(formatted_tips)}
          </div>
          <form hx-post="/ui/questions/{question_id}/human-review" hx-target="#response-{question_id}" hx-swap="innerHTML" style="margin-top: .6rem;">
            <input type="hidden" name="question_id" value="{question_id}">
            <input type="hidden" name="run_id" value="{escape(str(run_id))}">
            <input type="hidden" name="candidate_answer" value="{escape(answer)}">
            <div style="display:flex; gap: 0.8rem; flex-wrap:wrap; margin-bottom: 0.5rem;">
              <div style="flex:1; min-width:140px;">
                <label style="font-weight:bold; font-size:0.85rem; display:block;">Reviewer:</label>
                <input type="text" name="reviewer" value="User" style="width:100%; padding: 4px 6px;">
              </div>
              <div style="flex:1; min-width:140px;">
                <label style="font-weight:bold; font-size:0.85rem; display:block;">Decision:</label>
                <select name="decision" style="width:100%; padding: 4px 6px;">
                  <option value="Accept">Accept</option>
                  <option value="Partially Accept">Partially Accept</option>
                  <option value="Reject">Reject</option>
                </select>
              </div>
              <div style="width:100px;">
                <label style="font-weight:bold; font-size:0.85rem; display:block;">Score (0-100):</label>
                <input type="number" name="score" min="0" max="100" value="{score}" style="width:100%; padding: 4px 6px;">
              </div>
            </div>
            <div style="margin-bottom: 0.5rem;">
              <label style="font-weight:bold; font-size:0.85rem; display:block;">Final Feedback:</label>
              <textarea name="feedback" style="width:100%; min-height:45px;">{escape(raw_feedback_str)}</textarea>
            </div>
            <div style="margin-bottom: 0.5rem;">
              <label style="font-weight:bold; font-size:0.85rem; display:block;">Improvement Tips:</label>
              <input type="text" name="improvement_tips" value="{escape(raw_tips_str)}" style="width:100%; padding: 4px 6px;">
            </div>
            <div style="margin-bottom: 0.5rem;">
              <label style="font-weight:bold; font-size:0.85rem; display:block;">Reviewer Notes / Rationale:</label>
              <input type="text" name="rationale" value="Approved by user after 15 iterations." style="width:100%; padding: 4px 6px;">
            </div>
            <button type="submit" style="background:#d97706; color:white; font-weight:bold; padding: 6px 14px; border:none; border-radius:4px; cursor:pointer;">
              Submit Human Evaluation Decision
            </button>
          </form>
        </div>
        """

    if payload.get("mode") in {"multi-agent", "multi-agent-loop15"}:
        review = payload.get("review") or {}
        iterations = payload.get("iterations", 1)
        verdict = str(review.get("verdict", "approved")).upper()
        verdict_color = "#059669" if verdict == "APPROVED" else "#d97706"
        return f"""
        <div class="card" style="background:#f8fafc; border: 1px solid #cbd5e1; margin-top: .6rem;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>Release 2 Multi-Agent Coordinated Evaluation</strong>
            <div>
              <span style="background:{verdict_color}; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem; margin-right: 4px;">
                Iterations: {iterations} | {escape(verdict)}
              </span>
              <span style="background:#059669; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.85rem; font-weight:bold;">
                Score: {score}/100
              </span>
            </div>
          </div>
          <div style="margin: .5rem 0;"><strong>Worker Assessment:</strong> {formatted_fb}</div>
          <p style="margin: .5rem 0;"><strong>Improvement Tips:</strong> {escape(formatted_tips)}</p>
          <div style="background:#ffffff; border-radius: 6px; padding: .6rem; border: 1px solid #e2e8f0; font-size: 0.85rem;">
            <strong>Reviewer Audit ({review.get('score', 86)}/100):</strong> {escape(str(review.get('critique', 'Verified quality.')))}
          </div>
        </div>
        """

    sources = ", ".join(str(source) for source in payload.get("sources", [])) or "No sources returned"
    return f"""
    <div class="card">
      <strong>Score:</strong> {score}<br>
      <strong>Feedback:</strong> {formatted_fb}<br>
      <strong>Improvement tips:</strong> {formatted_tips}
    <br><strong>Grounding confidence:</strong> {escape(payload.get("confidence", "unknown"))}
    <br><strong>Sources:</strong> {escape(sources)}
    </div>
    """


@app.post("/ui/questions/<int:question_id>/human-review")
def ui_question_human_review(question_id: int):
    decision = request.form.get("decision", "Accept")
    reviewer = request.form.get("reviewer", "User").strip() or "User"
    rationale = request.form.get("rationale", "").strip()
    run_id = request.form.get("run_id", "").strip()
    candidate_answer = request.form.get("candidate_answer", "").strip()
    feedback = request.form.get("feedback", "").strip()
    tips = request.form.get("improvement_tips", "").strip()
    score = float(request.form.get("score", 75))

    try:
        payload, status = backend_request(
            "POST",
            f"/api/v1/interview-questions/{question_id}/human-review",
            json_body={
                "run_id": run_id,
                "decision": decision,
                "reviewer": reviewer,
                "rationale": rationale,
                "candidate_answer": candidate_answer,
                "feedback": feedback,
                "improvement_tips": tips,
                "score": score,
            },
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return f'<div class="card">{error}</div>'

    if status != 200:
        message = payload.get("error", "Human review could not be recorded.") if isinstance(payload, dict) else "Human review failed."
        return f'<div class="card">{message}</div>'

    if decision == "Reject":
        return f"""
        <div class="card" style="border-left: 4px solid #ef4444; background:#fef2f2; margin-top: .6rem;">
          <strong style="color:#b91c1c;">❌ Evaluation Rejected by Human Reviewer ({escape(reviewer)})</strong>
          <p style="margin: 0.3rem 0 0 0; font-size: 0.9rem;">
            {escape(rationale or 'Evaluation discarded. You may re-submit your answer.')}
          </p>
        </div>
        """

    final_score = payload.get("score", score)
    formatted_fb, formatted_tips = format_assessment_content(payload.get("feedback", feedback), payload.get("improvement_tips", tips))
    return f"""
    <div class="card" style="background:#f8fafc; border: 1px solid #cbd5e1; margin-top: .6rem;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <strong>Release 2 Multi-Agent Coordinated Evaluation</strong>
        <div>
          <span style="background:#059669; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.8rem; margin-right: 4px;">
            Human Review: {escape(decision.upper())}
          </span>
          <span style="background:#059669; color:white; padding: 2px 8px; border-radius: 999px; font-size: 0.85rem; font-weight:bold;">
            Score: {final_score}/100
          </span>
        </div>
      </div>
      <div style="margin: .5rem 0;"><strong>Final Feedback:</strong> {formatted_fb}</div>
      <p style="margin: .5rem 0;"><strong>Improvement Tips:</strong> {escape(formatted_tips)}</p>
      <div style="background:#ecfdf5; border-radius: 6px; padding: .6rem; border: 1px solid #a7f3d0; font-size: 0.85rem;">
        <strong>Human Decision ({escape(reviewer)}):</strong> {escape(rationale or 'Approved by human reviewer.')}
      </div>
    </div>
    """


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "student-3-frontend"}), 200


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Frontend route not found."}), 404


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
