from pathlib import Path
import os
import sqlite3

from flask import Flask, jsonify, request

from init_db import initialise_database


# ---------------------------------------------------------
# Application and database configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "candidate_data.db"

DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))

app = Flask(__name__)

ALLOWED_PROFICIENCY_LEVELS = {
    "Beginner",
    "Intermediate",
    "Advanced",
    "Expert",
}


# ---------------------------------------------------------
# Database helpers
# ---------------------------------------------------------

def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=5)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def row_to_dict(row):
    if row is None:
        return None

    return dict(row)


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def profile_exists(connection, profile_id):
    row = connection.execute(
        """
        SELECT id
        FROM candidate_profiles
        WHERE id = ?
        """,
        (profile_id,),
    ).fetchone()

    return row is not None


# ---------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------

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


def validate_profile_data(data):

    error = validate_required_text(
        data,
        [
            "full_name",
            "email",
            "target_role",
            "career_summary",
        ],
    )

    if error:
        return error

    email = data["email"].strip()

    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return "email must be a valid email address."

    return None


def validate_resume_data(data):

    error = validate_required_text(
        data,
        [
            "title",
            "content",
        ],
    )

    if error:
        return error

    profile_id = data.get("candidate_profile_id")

    if not isinstance(profile_id, int) or profile_id <= 0:
        return "candidate_profile_id must be a positive integer."

    is_primary = data.get("is_primary", 0)

    if isinstance(is_primary, bool):
        return None

    if is_primary not in (0, 1):
        return "is_primary must be 0, 1, true, or false."

    return None


def validate_skill_data(data):

    error = validate_required_text(
        data,
        [
            "skill_name",
            "proficiency_level",
        ],
    )

    if error:
        return error

    profile_id = data.get("candidate_profile_id")

    if not isinstance(profile_id, int) or profile_id <= 0:
        return "candidate_profile_id must be a positive integer."

    proficiency = data["proficiency_level"].strip()

    if proficiency not in ALLOWED_PROFICIENCY_LEVELS:
        return (
            "proficiency_level must be one of: "
            "Beginner, Intermediate, Advanced, Expert."
        )

    years_experience = data.get("years_experience", 0)

    if isinstance(years_experience, bool):
        return "years_experience must be a non-negative number."

    if not isinstance(years_experience, (int, float)):
        return "years_experience must be a non-negative number."

    if years_experience < 0:
        return "years_experience must be a non-negative number."

    return None


def normalise_is_primary(value):
    if isinstance(value, bool):
        return int(value)

    return value


# ---------------------------------------------------------
# Error handlers
# ---------------------------------------------------------

@app.errorhandler(404)
def handle_404(_error):
    return jsonify(
        {
            "error": "Endpoint not found.",
        }
    ), 404


@app.errorhandler(405)
def handle_405(_error):
    return jsonify(
        {
            "error": "Method not allowed.",
        }
    ), 405


@app.errorhandler(500)
def handle_500(_error):
    return jsonify(
        {
            "error": "Internal database service error.",
        }
    ), 500


# ---------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------

@app.get("/health")
def health():

    try:

        connection = get_connection()

        try:
            connection.execute("SELECT 1")

        finally:
            connection.close()

        return jsonify(
            {
                "status": "healthy",
                "service": "student-2-database",
            }
        ), 200

    except sqlite3.Error:

        return jsonify(
            {
                "status": "unhealthy",
                "service": "student-2-database",
            }
        ), 503


# =========================================================
# CandidateProfile CRUD
# =========================================================

@app.get("/api/v1/profiles")
def get_profiles():

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                full_name,
                email,
                target_role,
                career_summary,
                created_at,
                updated_at
            FROM candidate_profiles
            ORDER BY id
            """
        ).fetchall()

        return jsonify(rows_to_dicts(rows)), 200

    finally:
        connection.close()


@app.get("/api/v1/profiles/<int:profile_id>")
def get_profile(profile_id):

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                full_name,
                email,
                target_role,
                career_summary,
                created_at,
                updated_at
            FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        if row is None:

            return jsonify(
                {
                    "error": "Profile not found.",
                }
            ), 404

        return jsonify(row_to_dict(row)), 200

    finally:
        connection.close()


@app.post("/api/v1/profiles")
def create_profile():

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_profile_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO candidate_profiles (
                full_name,
                email,
                target_role,
                career_summary
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                data["full_name"].strip(),
                data["email"].strip(),
                data["target_role"].strip(),
                data["career_summary"].strip(),
            ),
        )

        connection.commit()

        profile_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT *
            FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 201

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": "A profile with this email already exists.",
            }
        ), 409

    finally:
        connection.close()


@app.put("/api/v1/profiles/<int:profile_id>")
def update_profile(profile_id):

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_profile_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Profile not found.",
                }
            ), 404

        connection.execute(
            """
            UPDATE candidate_profiles
            SET
                full_name = ?,
                email = ?,
                target_role = ?,
                career_summary = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data["full_name"].strip(),
                data["email"].strip(),
                data["target_role"].strip(),
                data["career_summary"].strip(),
                profile_id,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT *
            FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 200

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": "A profile with this email already exists.",
            }
        ), 409

    finally:
        connection.close()


@app.delete("/api/v1/profiles/<int:profile_id>")
def delete_profile(profile_id):

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Profile not found.",
                }
            ), 404

        connection.execute(
            """
            DELETE FROM candidate_profiles
            WHERE id = ?
            """,
            (profile_id,),
        )

        connection.commit()

        return jsonify(
            {
                "message": "Profile deleted successfully.",
                "id": profile_id,
            }
        ), 200

    finally:
        connection.close()


# =========================================================
# Resume CRUD
# =========================================================

@app.get("/api/v1/resumes")
def get_resumes():

    profile_id = request.args.get(
        "candidate_profile_id",
        type=int,
    )

    connection = get_connection()

    try:

        if profile_id is None:

            rows = connection.execute(
                """
                SELECT
                    id,
                    candidate_profile_id,
                    title,
                    content,
                    is_primary,
                    created_at,
                    updated_at
                FROM resumes
                ORDER BY id
                """
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT
                    id,
                    candidate_profile_id,
                    title,
                    content,
                    is_primary,
                    created_at,
                    updated_at
                FROM resumes
                WHERE candidate_profile_id = ?
                ORDER BY id
                """,
                (profile_id,),
            ).fetchall()

        return jsonify(rows_to_dicts(rows)), 200

    finally:
        connection.close()


@app.get("/api/v1/resumes/<int:resume_id>")
def get_resume(resume_id):

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                candidate_profile_id,
                title,
                content,
                is_primary,
                created_at,
                updated_at
            FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        ).fetchone()

        if row is None:

            return jsonify(
                {
                    "error": "Resume not found.",
                }
            ), 404

        return jsonify(row_to_dict(row)), 200

    finally:
        connection.close()


@app.post("/api/v1/resumes")
def create_resume():

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_resume_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        if not profile_exists(
            connection,
            data["candidate_profile_id"],
        ):

            return jsonify(
                {
                    "error": "Candidate profile not found.",
                }
            ), 404

        is_primary = normalise_is_primary(
            data.get("is_primary", 0)
        )

        cursor = connection.execute(
            """
            INSERT INTO resumes (
                candidate_profile_id,
                title,
                content,
                is_primary
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                data["candidate_profile_id"],
                data["title"].strip(),
                data["content"].strip(),
                is_primary,
            ),
        )

        connection.commit()

        resume_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT *
            FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 201

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": (
                    "This candidate already has a resume "
                    "with the same title."
                ),
            }
        ), 409

    finally:
        connection.close()


@app.put("/api/v1/resumes/<int:resume_id>")
def update_resume(resume_id):

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_resume_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Resume not found.",
                }
            ), 404

        if not profile_exists(
            connection,
            data["candidate_profile_id"],
        ):

            return jsonify(
                {
                    "error": "Candidate profile not found.",
                }
            ), 404

        is_primary = normalise_is_primary(
            data.get("is_primary", 0)
        )

        connection.execute(
            """
            UPDATE resumes
            SET
                candidate_profile_id = ?,
                title = ?,
                content = ?,
                is_primary = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data["candidate_profile_id"],
                data["title"].strip(),
                data["content"].strip(),
                is_primary,
                resume_id,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT *
            FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 200

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": (
                    "This candidate already has a resume "
                    "with the same title."
                ),
            }
        ), 409

    finally:
        connection.close()


@app.delete("/api/v1/resumes/<int:resume_id>")
def delete_resume(resume_id):

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Resume not found.",
                }
            ), 404

        connection.execute(
            """
            DELETE FROM resumes
            WHERE id = ?
            """,
            (resume_id,),
        )

        connection.commit()

        return jsonify(
            {
                "message": "Resume deleted successfully.",
                "id": resume_id,
            }
        ), 200

    finally:
        connection.close()


# =========================================================
# CandidateSkill CRUD
# =========================================================

@app.get("/api/v1/skills")
def get_skills():

    profile_id = request.args.get(
        "candidate_profile_id",
        type=int,
    )

    connection = get_connection()

    try:

        if profile_id is None:

            rows = connection.execute(
                """
                SELECT
                    id,
                    candidate_profile_id,
                    skill_name,
                    proficiency_level,
                    years_experience,
                    created_at,
                    updated_at
                FROM candidate_skills
                ORDER BY id
                """
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT
                    id,
                    candidate_profile_id,
                    skill_name,
                    proficiency_level,
                    years_experience,
                    created_at,
                    updated_at
                FROM candidate_skills
                WHERE candidate_profile_id = ?
                ORDER BY id
                """,
                (profile_id,),
            ).fetchall()

        return jsonify(rows_to_dicts(rows)), 200

    finally:
        connection.close()


@app.get("/api/v1/skills/<int:skill_id>")
def get_skill(skill_id):

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                candidate_profile_id,
                skill_name,
                proficiency_level,
                years_experience,
                created_at,
                updated_at
            FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        ).fetchone()

        if row is None:

            return jsonify(
                {
                    "error": "Skill not found.",
                }
            ), 404

        return jsonify(row_to_dict(row)), 200

    finally:
        connection.close()


@app.post("/api/v1/skills")
def create_skill():

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_skill_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        if not profile_exists(
            connection,
            data["candidate_profile_id"],
        ):

            return jsonify(
                {
                    "error": "Candidate profile not found.",
                }
            ), 404

        cursor = connection.execute(
            """
            INSERT INTO candidate_skills (
                candidate_profile_id,
                skill_name,
                proficiency_level,
                years_experience
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                data["candidate_profile_id"],
                data["skill_name"].strip(),
                data["proficiency_level"].strip(),
                data.get("years_experience", 0),
            ),
        )

        connection.commit()

        skill_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT *
            FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 201

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": (
                    "This candidate already has "
                    "a skill with the same name."
                ),
            }
        ), 409

    finally:
        connection.close()


@app.put("/api/v1/skills/<int:skill_id>")
def update_skill(skill_id):

    data = get_json_body()

    if data is None:

        return jsonify(
            {
                "error": "A valid JSON body is required.",
            }
        ), 400

    validation_error = validate_skill_data(data)

    if validation_error:

        return jsonify(
            {
                "error": validation_error,
            }
        ), 400

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Skill not found.",
                }
            ), 404

        if not profile_exists(
            connection,
            data["candidate_profile_id"],
        ):

            return jsonify(
                {
                    "error": "Candidate profile not found.",
                }
            ), 404

        connection.execute(
            """
            UPDATE candidate_skills
            SET
                candidate_profile_id = ?,
                skill_name = ?,
                proficiency_level = ?,
                years_experience = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data["candidate_profile_id"],
                data["skill_name"].strip(),
                data["proficiency_level"].strip(),
                data.get("years_experience", 0),
                skill_id,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT *
            FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        ).fetchone()

        return jsonify(row_to_dict(row)), 200

    except sqlite3.IntegrityError:

        connection.rollback()

        return jsonify(
            {
                "error": (
                    "This candidate already has "
                    "a skill with the same name."
                ),
            }
        ), 409

    finally:
        connection.close()


@app.delete("/api/v1/skills/<int:skill_id>")
def delete_skill(skill_id):

    connection = get_connection()

    try:

        existing = connection.execute(
            """
            SELECT id
            FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        ).fetchone()

        if existing is None:

            return jsonify(
                {
                    "error": "Skill not found.",
                }
            ), 404

        connection.execute(
            """
            DELETE FROM candidate_skills
            WHERE id = ?
            """,
            (skill_id,),
        )

        connection.commit()

        return jsonify(
            {
                "message": "Skill deleted successfully.",
                "id": skill_id,
            }
        ), 200

    finally:
        connection.close()


# ---------------------------------------------------------
# Application entry point
# ---------------------------------------------------------

if __name__ == "__main__":

    initialise_database()

    port = int(
        os.getenv(
            "PORT",
            "5002",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )