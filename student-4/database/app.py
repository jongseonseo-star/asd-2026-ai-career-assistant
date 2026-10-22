from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from init_db import initialise_database

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "data" / "jobs.db")))
PORT = int(os.getenv("PORT", "5402"))
app = Flask(__name__)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("A valid JSON object is required.")
    return value


def required_text(data: dict[str, Any], name: str, limit: int = 4000) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()[:limit]


def positive_int(data: dict[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def company_payload(data: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(required_text(data, field, 250) for field in ("name", "industry", "location", "website"))


def job_payload(data: dict[str, Any]) -> tuple[Any, ...]:
    salary_min = data.get("salary_min")
    salary_max = data.get("salary_max")
    for name, value in (("salary_min", salary_min), ("salary_max", salary_max)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer or null.")
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise ValueError("salary_min cannot exceed salary_max.")
    return (
        positive_int(data, "company_id"), required_text(data, "title", 200),
        required_text(data, "location", 200), required_text(data, "employment_type", 50),
        required_text(data, "experience_level", 50), required_text(data, "description"),
        salary_min, salary_max, required_text(data, "closing_date", 20),
        required_text(data, "status", 30),
    )


def skill_payload(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        positive_int(data, "job_posting_id"),
        required_text(data, "skill_name", 120),
        required_text(data, "importance", 30),
    )


@app.errorhandler(ValueError)
def invalid(error: ValueError):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(sqlite3.IntegrityError)
def conflict(error: sqlite3.IntegrityError):
    return jsonify({"error": "Database constraint failed.", "detail": str(error)}), 409


@app.get("/health")
def health():
    with connect() as connection:
        connection.execute("SELECT 1").fetchone()
    return jsonify({"status": "healthy", "service": "student-4-database"})


@app.get("/api/v1/stats")
def stats():
    with connect() as connection:
        counts = {
            "companies": connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "job_postings": connection.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0],
            "job_skills": connection.execute("SELECT COUNT(*) FROM job_skills").fetchone()[0],
        }
    return jsonify(counts)


RESOURCE_CONFIG = {
    "companies": {
        "payload": company_payload,
        "select": "SELECT * FROM companies",
        "select_by_id": "SELECT * FROM companies WHERE id=?",
        "insert": (
            "INSERT INTO companies (name, industry, location, website) "
            "VALUES (?, ?, ?, ?)"
        ),
        "update": "UPDATE companies SET name=?, industry=?, location=?, website=? WHERE id=?",
        "delete": "DELETE FROM companies WHERE id=?",
    },
    "job_postings": {
        "payload": job_payload,
        "select": "SELECT * FROM job_postings",
        "select_by_id": "SELECT * FROM job_postings WHERE id=?",
        "insert": (
            "INSERT INTO job_postings "
            "(company_id, title, location, employment_type, experience_level, "
            "description, salary_min, salary_max, closing_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ),
        "update": (
            "UPDATE job_postings SET company_id=?, title=?, location=?, "
            "employment_type=?, experience_level=?, description=?, salary_min=?, "
            "salary_max=?, closing_date=?, status=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?"
        ),
        "delete": "DELETE FROM job_postings WHERE id=?",
    },
    "job_skills": {
        "payload": skill_payload,
        "select": "SELECT * FROM job_skills",
        "select_by_id": "SELECT * FROM job_skills WHERE id=?",
        "insert": (
            "INSERT INTO job_skills (job_posting_id, skill_name, importance) "
            "VALUES (?, ?, ?)"
        ),
        "update": (
            "UPDATE job_skills SET job_posting_id=?, skill_name=?, importance=? WHERE id=?"
        ),
        "delete": "DELETE FROM job_skills WHERE id=?",
    },
}


@app.route("/api/v1/<resource>", methods=["GET", "POST"])
def collection(resource: str):
    config = RESOURCE_CONFIG.get(resource)
    if config is None:
        return jsonify({"error": "Resource not found."}), 404
    with connect() as connection:
        if request.method == "GET":
            query = config["select"]
            params: list[Any] = []
            if resource == "job_postings" and request.args.get("q"):
                term = f"%{request.args['q'].strip()}%"
                query += " WHERE title LIKE ? OR description LIKE ? OR location LIKE ?"
                params = [term, term, term]
            rows = connection.execute(query + " ORDER BY id", params).fetchall()
            return jsonify([dict(row) for row in rows])
        values = config["payload"](body())
        cursor = connection.execute(config["insert"], values)
        row = connection.execute(config["select_by_id"], (cursor.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201


@app.route("/api/v1/<resource>/<int:item_id>", methods=["GET", "PUT", "DELETE"])
def item(resource: str, item_id: int):
    config = RESOURCE_CONFIG.get(resource)
    if config is None:
        return jsonify({"error": "Resource not found."}), 404
    with connect() as connection:
        existing = connection.execute(config["select_by_id"], (item_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Record not found."}), 404
        if request.method == "GET":
            return jsonify(dict(existing))
        if request.method == "DELETE":
            connection.execute(config["delete"], (item_id,))
            return "", 204
        values = config["payload"](body())
        connection.execute(config["update"], (*values, item_id))
        updated = connection.execute(config["select_by_id"], (item_id,)).fetchone()
        return jsonify(dict(updated))


initialise_database(DB_PATH)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)  # noqa: S104 - Other Docker containers must reach this service.
