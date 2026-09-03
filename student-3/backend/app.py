from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request

BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts"

DATABASE_API_URL = os.getenv("DATABASE_API_URL", "http://127.0.0.1:5002").rstrip("/")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
PORT = int(os.getenv("PORT", "5001"))
DATABASE_TIMEOUT = float(os.getenv("DATABASE_TIMEOUT_SECONDS", "5"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

app = Flask(__name__)
session = requests.Session()


class ClientInputError(Exception):
    pass


class DependencyError(Exception):
    def __init__(self, dependency: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.dependency = dependency
        self.message = message
        self.status_code = status_code


@app.errorhandler(ClientInputError)
def handle_client_input(error: ClientInputError):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(DependencyError)
def handle_dependency(error: DependencyError):
    return jsonify({"error": error.message, "dependency": error.dependency}), error.status_code


@app.errorhandler(404)
def handle_404(_error):
    return jsonify({"error": "Endpoint not found."}), 404


@app.errorhandler(405)
def handle_405(_error):
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def handle_500(_error):
    return jsonify({"error": "Internal backend service error."}), 500


def require_json_object() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ClientInputError("A valid JSON object is required.")
    return data


def require_text(data: dict[str, Any], field: str, maximum_length: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ClientInputError(f"{field} is required.")
    value = value.strip()
    if len(value) > maximum_length:
        raise ClientInputError(f"{field} must not exceed {maximum_length} characters.")
    return value


def require_positive_integer(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClientInputError(f"{field} must be a positive integer.")
    return value


def load_prompt(file_name: str) -> str:
    try:
        text = (PROMPTS_DIR / file_name).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise DependencyError("prompt-assets", f"Unable to load prompt asset: {file_name}.", 500) from error
    if not text:
        raise DependencyError("prompt-assets", f"Prompt asset is empty: {file_name}.", 500)
    return text


def database_request(method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> tuple[Any, int]:
    try:
        response = session.request(method, f"{DATABASE_API_URL}{path}", json=json_body, params=params, timeout=DATABASE_TIMEOUT)
    except requests.Timeout as error:
        raise DependencyError("student-3-database", "Database service request timed out.") from error
    except requests.RequestException as error:
        raise DependencyError("student-3-database", "Database service is unavailable.") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise DependencyError("student-3-database", "Database service returned non-JSON data.", 502) from error

    if response.status_code >= 500:
        raise DependencyError("student-3-database", "Database service returned an internal error.")
    return payload, response.status_code


def proxy_database(method: str, path: str, *, json_body: dict[str, Any] | None = None, include_query: bool = False):
    params = request.args.to_dict(flat=True) if include_query else None
    payload, status = database_request(method, path, json_body=json_body, params=params)
    return jsonify(payload), status


def get_ollama_models() -> list[str]:
    try:
        response = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as error:
        raise DependencyError("ollama", "Ollama status request timed out.") from error
    except (requests.RequestException, ValueError) as error:
        raise DependencyError("ollama", "Ollama is unavailable or returned invalid data.") from error
    return [model["name"] for model in payload.get("models", []) if isinstance(model, dict) and model.get("name")]


def call_ollama(system_prompt: str, user_prompt: str) -> str:
    body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.2, "num_predict": 500},
    }
    try:
        response = session.post(f"{OLLAMA_BASE_URL}/api/chat", json=body, timeout=OLLAMA_TIMEOUT)
    except requests.Timeout as error:
        raise DependencyError("ollama", "Ollama interview generation timed out.") from error
    except requests.RequestException as error:
        raise DependencyError("ollama", "Ollama is unavailable.") from error

    if response.status_code != 200:
        raise DependencyError("ollama", f"Ollama could not run '{OLLAMA_MODEL}'. Check that the model is installed.")

    try:
        content = response.json().get("message", {}).get("content", "").strip()
    except ValueError as error:
        raise DependencyError("ollama", "Ollama returned non-JSON data.", 502) from error

    if not content:
        raise DependencyError("ollama", "Ollama returned an empty response.", 502)
    return content


def parse_json_text(raw_text: str) -> Any:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    return json.loads(cleaned)


@app.get("/")
def service_information():
    return jsonify({
        "service": "student-3-backend",
        "feature": "Interview Preparation Management",
        "release": "Release 0",
        "database_api_url": DATABASE_API_URL,
        "ollama_model": OLLAMA_MODEL,
    }), 200


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "student-3-backend"}), 200


@app.get("/ready")
def readiness():
    database_health, status = database_request("GET", "/health")
    if status != 200:
        raise DependencyError("student-3-database", "Database service is not ready.")
    return jsonify({"status": "ready", "service": "student-3-backend", "dependencies": {"database": database_health}}), 200


@app.get("/api/v1/ai/status")
def ai_status():
    models = get_ollama_models()
    return jsonify({
        "status": "available",
        "runtime": "Ollama",
        "configured_model": OLLAMA_MODEL,
        "configured_model_available": OLLAMA_MODEL in models,
        "installed_models": models,
    }), 200


@app.route("/api/v1/interview-sessions", methods=["GET", "POST"])
def interview_sessions_collection():
    if request.method == "GET":
        return proxy_database("GET", "/api/v1/interview-sessions", include_query=True)
    return proxy_database("POST", "/api/v1/interview-sessions", json_body=require_json_object())


@app.route("/api/v1/interview-sessions/<int:session_id>", methods=["GET", "PUT", "DELETE"])
def interview_session_item(session_id: int):
    path = f"/api/v1/interview-sessions/{session_id}"
    if request.method == "GET":
        return proxy_database("GET", path)
    if request.method == "DELETE":
        return proxy_database("DELETE", path)
    return proxy_database("PUT", path, json_body=require_json_object())


@app.route("/api/v1/interview-sessions/<int:session_id>/questions", methods=["GET"])
def interview_session_questions(session_id: int):
    return proxy_database("GET", f"/api/v1/interview-sessions/{session_id}/questions")


@app.route("/api/v1/interview-sessions/<int:session_id>/generate-questions", methods=["POST"])
def generate_questions_for_session(session_id: int):
    data = require_json_object()
    session_payload, status = database_request("GET", f"/api/v1/interview-sessions/{session_id}")
    if status != 200:
        return jsonify(session_payload), status

role = require_text(data, "target_role", 200) if "target_role" in data else str(session_payload.get("target_role", "General role")).strip()
raw_interview_type = data.get("interview_type", session_payload.get("interview_type", "general"))
interview_type = str(raw_interview_type).strip() or "general"
    if isinstance(question_count, bool) or not isinstance(question_count, int):
        raise ClientInputError("question_count must be an integer.")
    if question_count < 1 or question_count > 10:
        raise ClientInputError("question_count must be between 1 and 10.")

    prompt = f"{load_prompt('question_generation_task.txt')}\n\nCONTROLLED CONTEXT\n{json.dumps({'session_id': session_id, 'target_role': role, 'interview_type': interview_type, 'question_count': question_count}, ensure_ascii=False, indent=2)}"
    model_output = call_ollama(load_prompt('system_prompt.txt'), prompt)
    parsed = parse_json_text(model_output)
    items = parsed.get("questions", []) if isinstance(parsed, dict) else []
    if not isinstance(items, list) or not items:
        raise DependencyError("ollama", "Ollama did not return any interview questions.", 502)

    created_questions = []
    for item in items[:question_count]:
        question = item if isinstance(item, dict) else {"question": str(item)}
        question_text = question.get("question") or question.get("question_text") or str(question)
        category = question.get("category") or interview_type or "general"
        record, record_status = database_request(
            "POST",
            "/api/v1/interview-questions",
            json_body={
                "session_id": session_id,
                "category": str(category).strip()[:80],
                "question_text": str(question_text).strip()[:3000],
            },
        )
        if record_status != 201:
            return jsonify(record), record_status
        created_questions.append(record)

    return jsonify({
        "session_id": session_id,
        "questions": created_questions,
        "generated_questions": created_questions,
        "count": len(created_questions),
    }), 200


@app.route("/api/v1/interview-questions", methods=["GET", "POST"])
def interview_questions_collection():
    if request.method == "GET":
        return proxy_database("GET", "/api/v1/interview-questions", include_query=True)
    return proxy_database("POST", "/api/v1/interview-questions", json_body=require_json_object())


@app.route("/api/v1/interview-questions/<int:question_id>", methods=["GET", "PUT", "DELETE"])
def interview_question_item(question_id: int):
    path = f"/api/v1/interview-questions/{question_id}"
    if request.method == "GET":
        return proxy_database("GET", path)
    if request.method == "DELETE":
        return proxy_database("DELETE", path)
    return proxy_database("PUT", path, json_body=require_json_object())


@app.route("/api/v1/interview-responce", methods=["GET", "POST"])
def interview_responses_collection():
    if request.method == "GET":
        return proxy_database("GET", "/api/v1/interview-responce", include_query=True)
    return proxy_database("POST", "/api/v1/interview-responce", json_body=require_json_object())


@app.route("/api/v1/interview-questions/<int:question_id>/evaluate-answer", methods=["POST"])
def evaluate_answer(question_id: int):
    data = require_json_object()
    if "answer" in data:
        candidate_answer = require_text(data, "answer", 12000)
    else:
        candidate_answer = require_text(data, "user_answer", 12000)
    question_payload, question_status = database_request("GET", f"/api/v1/interview-questions/{question_id}")
    if question_status != 200:
        return jsonify(question_payload), question_status
    session_id = question_payload.get("session_id")
    session_payload, session_status = database_request("GET", f"/api/v1/interview-sessions/{session_id}")
    if session_status != 200:
        return jsonify(session_payload), session_status

    prompt = f"{load_prompt('response_evaluation_task.txt')}\n\nCONTROLLED CONTEXT\n{json.dumps({'target_role': session_payload.get('target_role', 'General'), 'question': question_payload.get('question_text', ''), 'candidate_answer': candidate_answer}, ensure_ascii=False, indent=2)}"
    model_output = call_ollama(load_prompt('system_prompt.txt'), prompt)
    parsed = parse_json_text(model_output)
    if not isinstance(parsed, dict):
        raise DependencyError("ollama", "Ollama returned an invalid evaluation payload.", 502)

score = parsed.get("score", 0)
if isinstance(score, bool) or not isinstance(score, (int, float)):
    raise DependencyError("ollama", "Ollama evaluation did not include a numeric score.", 502)
score = float(score)
score = min(max(score, 0.0), 100.0)
feedback = parsed.get("feedback") or "The response was submitted for review."
tips_raw = parsed.get("improvement_tips") or "Keep practising with more concrete examples and clearer structure."
if isinstance(tips_raw, list):
    tips = "; ".join(str(item).strip() for item in tips_raw if str(item).strip())
else:
    tips = str(tips_raw).strip()

response_payload, response_status = database_request(
    "POST",
    "/api/v1/interview-responce",
    json_body={
        "question_id": question_id,
        "user_answer": candidate_answer,
        "ai_feedback": str(feedback).strip()[:4000],
        "score": score,
        "improvement_tips": str(tips).strip()[:4000],
    },
        },
    )
    if response_status != 201:
        return jsonify(response_payload), response_status

    answers_payload, answers_status = database_request("GET", "/api/v1/interview-responce", params={"question_id": question_id})
    if answers_status == 200 and isinstance(answers_payload, list):
        average = sum(float(item.get("score", 0) or 0) for item in answers_payload) / len(answers_payload)
        update_payload, update_status = database_request("PUT", f"/api/v1/interview-sessions/{session_id}", json_body={"overall_score": round(average, 2)})
        if update_status != 200:
            return jsonify(update_payload), update_status

    return jsonify({
        "session_id": session_id,
        "question_id": question_id,
        "score": round(score, 2),
        "feedback": str(feedback).strip(),
        "improvement_tips": str(tips).strip(),
        "response": response_payload,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
