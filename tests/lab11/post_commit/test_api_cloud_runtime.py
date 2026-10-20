"""Lab 11 API tests for the AI-disabled cloud runtime."""

import os

import requests


INTERVIEW_SERVICE_URL = os.getenv("INTERVIEW_SERVICE_URL", "http://localhost:5301")


def test_service_health():
    response = requests.get(f"{INTERVIEW_SERVICE_URL}/health", timeout=5)

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_service_ready():
    response = requests.get(f"{INTERVIEW_SERVICE_URL}/ready", timeout=5)

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_interview_sessions_exist():
    response = requests.get(
        f"{INTERVIEW_SERVICE_URL}/api/v1/interview-sessions", timeout=5
    )

    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)
    assert len(sessions) > 0


def test_ai_status_is_disabled():
    response = requests.get(
        f"{INTERVIEW_SERVICE_URL}/api/v1/ai/status", timeout=5
    )

    assert response.status_code == 200
    status = response.json()
    assert status["status"] == "disabled"
    assert status["dependencies"]["ollama"]["status"] == "disabled"
    assert status["dependencies"]["mcp"]["status"] == "disabled"
    assert status["dependencies"]["rag"]["status"] == "disabled"
    assert status["dependencies"]["multi_agent"]["status"] == "disabled"


def test_question_generation_is_disabled():
    # Use a missing record so the test does not change sample data.
    response = requests.post(
        f"{INTERVIEW_SERVICE_URL}/api/v1/interview-sessions/999999/generate-questions",
        json={"mode": "ai"},
        timeout=5,
    )

    assert response.status_code == 503
    assert "disabled" in response.json()["error"].lower()


def test_answer_evaluation_is_disabled():
    response = requests.post(
        f"{INTERVIEW_SERVICE_URL}/api/v1/interview-questions/999999/evaluate-answer",
        json={"mode": "ai", "answer": "Lab 11 test answer"},
        timeout=5,
    )

    assert response.status_code == 503
    assert "disabled" in response.json()["error"].lower()


def test_multi_agent_status_is_disabled():
    response = requests.get(
        f"{INTERVIEW_SERVICE_URL}/api/v1/multi-agent/status", timeout=5
    )

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
