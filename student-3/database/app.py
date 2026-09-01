from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from flask import Flask, jsonify, request

try:
    from .init_db import initialise_database
except ImportError:  # pragma: no cover
    from init_db import initialise_database

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "interview_data.db"
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))

app = Flask(__name__)


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def session_exists(connection, session_id):
    row = connection.execute(
        "SELECT id FROM interview_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    return row is not None


def question_exists(connection, question_id):
    row = connection.execute(
        "SELECT id FROM interview_questions WHERE id = ?",
        (question_id,),
    ).fetchone()
    return row is not None


def get_json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    return data


def validate_required_text(data, fields):
    for field in fields:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"{field} is required."
    return None


def validate_session_data(data):
    error = validate_required_text(data, ["candidate_name", "target_role"])
    if error:
        return error
    interview_type = data.get("interview_type", "general")
    if not isinstance(interview_type, str) or not interview_type.strip():
        return "interview_type is required."
    return None


def validate_question_data(data):
    error = validate_required_text(data, ["question_text"])
    if error:
        return error
    session_id = data.get("session_id")
    if not isinstance(session_id, int) or session_id <= 0:
        return "session_id must be a positive integer."
    return None


def validate_response_data(data):
    error = validate_required_text(data, ["user_answer"])
    if error:
        return error
    question_id = data.get("question_id")
    if not isinstance(question_id, int) or question_id <= 0:
        return "question_id must be a positive integer."
    score = data.get("score", 0)
    if isinstance(score, bool):
        return "score must be a number."
    if not isinstance(score, (int, float)):
        return "score must be a number."
    if score < 0 or score > 100:
        return "score must be between 0 and 100."
    return None


@app.errorhandler(404)
def handle_404(_error):
    return jsonify({"error": "Endpoint not found."}), 404


@app.errorhandler(405)
def handle_405(_error):
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def handle_500(_error):
    return jsonify({"error": "Internal database service error."}), 500


@app.get("/health")
def health():
    try:
        connection = get_connection()
        try:
            connection.execute("SELECT 1")
        finally:
            connection.close()
        return jsonify({"status": "healthy", "service": "student-3-database"}), 200
    except sqlite3.Error:
        return jsonify({"status": "unhealthy", "service": "student-3-database"}), 503


@app.get("/api/v1/interview-sessions")
def get_sessions():
    connection = get_connection()
    try:
        candidate_name = request.args.get("candidate_name")
        target_role = request.args.get("target_role")
        query = "SELECT * FROM interview_sessions"
        params = []
        filters = []
        if candidate_name:
            filters.append("candidate_name LIKE ?")
            params.append(f"%{candidate_name}%")
        if target_role:
            filters.append("target_role LIKE ?")
            params.append(f"%{target_role}%")
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC"
        rows = connection.execute(query, params).fetchall()
        return jsonify(rows_to_dicts(rows)), 200
    finally:
        connection.close()


@app.post("/api/v1/interview-sessions")
def create_session():
    data = get_json_body()
    if data is None:
        return jsonify({"error": "A valid JSON object is required."}), 400
    error = validate_session_data(data)
    if error:
        return jsonify({"error": error}), 400

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO interview_sessions (
                candidate_name, target_role, interview_type, status, overall_score, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["candidate_name"].strip(),
                data["target_role"].strip(),
                data.get("interview_type", "general").strip(),
                data.get("status", "draft"),
                float(data.get("overall_score", 0) or 0),
                data.get("notes"),
            ),
        )
        connection.commit()
        created = connection.execute(
            "SELECT * FROM interview_sessions WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(row_to_dict(created)), 201
    finally:
        connection.close()


@app.route("/api/v1/interview-sessions/<int:session_id>", methods=["GET", "PUT", "DELETE"])
def session_item(session_id: int):
    connection = get_connection()
    try:
        if request.method == "GET":
            row = connection.execute(
                "SELECT * FROM interview_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return jsonify({"error": "Interview session not found."}), 404
            return jsonify(row_to_dict(row)), 200

        if request.method == "DELETE":
            cursor = connection.execute(
                "DELETE FROM interview_sessions WHERE id = ?",
                (session_id,),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return jsonify({"error": "Interview session not found."}), 404
            return jsonify({"deleted": True, "id": session_id}), 200

        data = get_json_body()
        if data is None:
            return jsonify({"error": "A valid JSON object is required."}), 400

        updates = []
        values = []
        for field in ["candidate_name", "target_role", "interview_type", "status", "notes"]:
            if field in data:
                updates.append(f"{field} = ?")
                values.append(data[field])
        if "overall_score" in data:
            score = data["overall_score"]
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                return jsonify({"error": "overall_score must be a number."}), 400
            updates.append("overall_score = ?")
            values.append(float(score))
        if not updates:
            return jsonify({"error": "No supported fields were provided."}), 400
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(session_id)
        connection.execute(
            f"UPDATE interview_sessions SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM interview_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return jsonify(row_to_dict(row)), 200
    finally:
        connection.close()


@app.get("/api/v1/interview-sessions/<int:session_id>/questions")
def get_session_questions(session_id: int):
    connection = get_connection()
    try:
        if not session_exists(connection, session_id):
            return jsonify({"error": "Interview session not found."}), 404
        rows = connection.execute(
            "SELECT * FROM interview_questions WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return jsonify(rows_to_dicts(rows)), 200
    finally:
        connection.close()


@app.route("/api/v1/interview-questions", methods=["GET", "POST"])
def questions_collection():
    if request.method == "GET":
        session_id = request.args.get("session_id")
        connection = get_connection()
        try:
            if session_id:
                rows = connection.execute(
                    "SELECT * FROM interview_questions WHERE session_id = ? ORDER BY id ASC",
                    (int(session_id),),
                ).fetchall()
                return jsonify(rows_to_dicts(rows)), 200
            rows = connection.execute("SELECT * FROM interview_questions ORDER BY id ASC").fetchall()
            return jsonify(rows_to_dicts(rows)), 200
        finally:
            connection.close()

    data = get_json_body()
    if data is None:
        return jsonify({"error": "A valid JSON object is required."}), 400
    error = validate_question_data(data)
    if error:
        return jsonify({"error": error}), 400

    connection = get_connection()
    try:
        if not session_exists(connection, data["session_id"]):
            return jsonify({"error": "Interview session not found."}), 404
        cursor = connection.execute(
            """
            INSERT INTO interview_questions (session_id, category, question_text)
            VALUES (?, ?, ?)
            """,
            (
                data["session_id"],
                data.get("category", "general").strip(),
                data["question_text"].strip(),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM interview_questions WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(row_to_dict(row)), 201
    finally:
        connection.close()


@app.route("/api/v1/interview-questions/<int:question_id>", methods=["GET", "PUT", "DELETE"])
def question_item(question_id: int):
    connection = get_connection()
    try:
        if request.method == "GET":
            row = connection.execute(
                "SELECT * FROM interview_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if row is None:
                return jsonify({"error": "Interview question not found."}), 404
            return jsonify(row_to_dict(row)), 200

        if request.method == "DELETE":
            cursor = connection.execute(
                "DELETE FROM interview_questions WHERE id = ?",
                (question_id,),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return jsonify({"error": "Interview question not found."}), 404
            return jsonify({"deleted": True, "id": question_id}), 200

        data = get_json_body()
        if data is None:
            return jsonify({"error": "A valid JSON object is required."}), 400
        updates = []
        values = []
        for field in ["category", "question_text"]:
            if field in data:
                updates.append(f"{field} = ?")
                values.append(data[field])
        if not updates:
            return jsonify({"error": "No supported fields were provided."}), 400
        values.append(question_id)
        connection.execute(
            f"UPDATE interview_questions SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM interview_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        return jsonify(row_to_dict(row)), 200
    finally:
        connection.close()


@app.route("/api/v1/interview-responce", methods=["GET", "POST"])
def responses_collection():
    if request.method == "GET":
        question_id = request.args.get("question_id")
        connection = get_connection()
        try:
            if question_id:
                rows = connection.execute(
                    "SELECT * FROM interview_responce WHERE question_id = ? ORDER BY id ASC",
                    (int(question_id),),
                ).fetchall()
                return jsonify(rows_to_dicts(rows)), 200
            rows = connection.execute("SELECT * FROM interview_responce ORDER BY id ASC").fetchall()
            return jsonify(rows_to_dicts(rows)), 200
        finally:
            connection.close()

    data = get_json_body()
    if data is None:
        return jsonify({"error": "A valid JSON object is required."}), 400
    error = validate_response_data(data)
    if error:
        return jsonify({"error": error}), 400

    connection = get_connection()
    try:
        if not question_exists(connection, data["question_id"]):
            return jsonify({"error": "Interview question not found."}), 404
        cursor = connection.execute(
            """
            INSERT INTO interview_responce (
                question_id, user_answer, ai_feedback, score, improvement_tips
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["question_id"],
                data["user_answer"].strip(),
                data.get("ai_feedback"),
                float(data.get("score", 0) or 0),
                data.get("improvement_tips"),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM interview_responce WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(row_to_dict(row)), 201
    finally:
        connection.close()


@app.route("/api/v1/interview-responce/<int:response_id>", methods=["GET", "PUT", "DELETE"])
def response_item(response_id: int):
    connection = get_connection()
    try:
        if request.method == "GET":
            row = connection.execute(
                "SELECT * FROM interview_responce WHERE id = ?",
                (response_id,),
            ).fetchone()
            if row is None:
                return jsonify({"error": "Interview response not found."}), 404
            return jsonify(row_to_dict(row)), 200

        if request.method == "DELETE":
            cursor = connection.execute(
                "DELETE FROM interview_responce WHERE id = ?",
                (response_id,),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return jsonify({"error": "Interview response not found."}), 404
            return jsonify({"deleted": True, "id": response_id}), 200

        data = get_json_body()
        if data is None:
            return jsonify({"error": "A valid JSON object is required."}), 400
        updates = []
        values = []
        for field in ["user_answer", "ai_feedback", "improvement_tips"]:
            if field in data:
                updates.append(f"{field} = ?")
                values.append(data[field])
        if "score" in data:
            score = data["score"]
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                return jsonify({"error": "score must be a number."}), 400
            updates.append("score = ?")
            values.append(float(score))
        if not updates:
            return jsonify({"error": "No supported fields were provided."}), 400
        values.append(response_id)
        connection.execute(
            f"UPDATE interview_responce SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM interview_responce WHERE id = ?",
            (response_id,),
        ).fetchone()
        return jsonify(row_to_dict(row)), 200
    finally:
        connection.close()


if __name__ == "__main__":
    initialise_database()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5002")), debug=False)
