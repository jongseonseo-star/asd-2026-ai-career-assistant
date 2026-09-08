from pathlib import Path
import os
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "interview_data.db"
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_tables(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_name TEXT NOT NULL,
            target_role TEXT NOT NULL,
            interview_type TEXT NOT NULL DEFAULT 'general',
            status TEXT NOT NULL DEFAULT 'draft',
            overall_score REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS interview_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            question_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS interview_responce (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            user_answer TEXT NOT NULL,
            ai_feedback TEXT,
            score REAL NOT NULL DEFAULT 0,
            improvement_tips TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES interview_questions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_questions_session
        ON interview_questions(session_id);

        CREATE INDEX IF NOT EXISTS idx_responce_question
        ON interview_responce(question_id);
        """
    )


def seed_sessions(connection):
    existing = connection.execute("SELECT COUNT(*) FROM interview_sessions").fetchone()[0]
    if existing > 0:
        return

    sessions = [
        (
            session_id,
            f"Candidate {session_id}",
            role,
            interview_type,
            "active" if session_id % 2 == 0 else "draft",
            0.0,
            f"Practice plan for {role} interviews.",
        )
        for session_id, (role, interview_type) in enumerate(
            [
                ("Software Engineer", "technical"),
                ("Product Manager", "behavioral"),
                ("Data Analyst", "technical"),
                ("UX Designer", "behavioral"),
                ("DevOps Engineer", "technical"),
                ("Project Manager", "behavioral"),
                ("QA Engineer", "technical"),
                ("Security Engineer", "technical"),
                ("Business Analyst", "behavioral"),
                ("Cloud Architect", "technical"),
            ],
            start=1,
        )
    ]

    questions = [
        (
            question_id,
            ((question_id - 1) // 2) + 1,
            "technical" if question_id % 2 else "behavioral",
            f"Practice interview question {question_id}: explain your approach and trade-offs.",
        )
        for question_id in range(1, 21)
    ]

    responses = [
        (
            response_id,
            response_id,
            f"Sample answer for interview question {response_id}.",
            "Clear answer with room for more concrete examples.",
            70.0 + (response_id % 21),
            "Add measurable results and discuss trade-offs.",
        )
        for response_id in range(1, 21)
    ]

    connection.executemany(
        """
        INSERT INTO interview_sessions (
            id, candidate_name, target_role, interview_type, status, overall_score, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        sessions,
    )

    connection.executemany(
        """
        INSERT INTO interview_questions (
            id, session_id, category, question_text
        ) VALUES (?, ?, ?, ?)
        """,
        questions,
    )

    connection.executemany(
        """
        INSERT INTO interview_responce (
            id, question_id, user_answer, ai_feedback, score, improvement_tips
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        responses,
    )


def initialise_database():
    connection = get_connection()
    try:
        create_tables(connection)
        seed_sessions(connection)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    initialise_database()
    print(f"Initialised interview database at {DB_PATH}")
