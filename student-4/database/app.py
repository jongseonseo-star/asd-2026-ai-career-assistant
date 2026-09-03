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
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("companies", "job_postings", "job_skills")
        }
    return jsonify(counts)


RESOURCE_CONFIG = {
    "companies": {
        "columns": "name, industry, location, website",
        "payload": company_payload,
        "update": "name=?, industry=?, location=?, website=?",
    },
    "job_postings": {
        "columns": "company_id, title, location, employment_type, experience_level, description, salary_min, salary_max, closing_date, status",
        "payload": job_payload,
        "update": "company_id=?, title=?, location=?, employment_type=?, experience_level=?, description=?, salary_min=?, salary_max=?, closing_date=?, status=?, updated_at=CURRENT_TIMESTAMP",
    },
    "job_skills": {
        "columns": "job_posting_id, skill_name, importance",
        "payload": skill_payload,
        "update": "job_posting_id=?, skill_name=?, importance=?",
    },
}


@app.route("/api/v1/<resource>", methods=["GET", "POST"])
def collection(resource: str):
    config = RESOURCE_CONFIG.get(resource)
    if config is None:
        return jsonify({"error": "Resource not found."}), 404
    with connect() as connection:
        if request.method == "GET":
            query = f"SELECT * FROM {resource}"
            params: list[Any] = []
            if resource == "job_postings" and request.args.get("q"):
                term = f"%{request.args['q'].strip()}%"
                query += " WHERE title LIKE ? OR description LIKE ? OR location LIKE ?"
                params = [term, term, term]
            rows = connection.execute(query + " ORDER BY id", params).fetchall()
            return jsonify([dict(row) for row in rows])
        values = config["payload"](body())
        placeholders = ",".join("?" for _ in values)
        cursor = connection.execute(
            f"INSERT INTO {resource} ({config['columns']}) VALUES ({placeholders})", values
        )
        row = connection.execute(f"SELECT * FROM {resource} WHERE id=?", (cursor.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201


@app.route("/api/v1/<resource>/<int:item_id>", methods=["GET", "PUT", "DELETE"])
def item(resource: str, item_id: int):
    config = RESOURCE_CONFIG.get(resource)
    if config is None:
        return jsonify({"error": "Resource not found."}), 404
    with connect() as connection:
        existing = connection.execute(f"SELECT * FROM {resource} WHERE id=?", (item_id,)).fetchone()
        if existing is None:
            return jsonify({"error": "Record not found."}), 404
        if request.method == "GET":
            return jsonify(dict(existing))
        if request.method == "DELETE":
            connection.execute(f"DELETE FROM {resource} WHERE id=?", (item_id,))
            return "", 204
        values = config["payload"](body())
        connection.execute(f"UPDATE {resource} SET {config['update']} WHERE id=?", (*values, item_id))
        updated = connection.execute(f"SELECT * FROM {resource} WHERE id=?", (item_id,)).fetchone()
        return jsonify(dict(updated))


initialise_database(DB_PATH)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
