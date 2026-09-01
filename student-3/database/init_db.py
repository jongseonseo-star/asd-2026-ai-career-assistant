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

    connection.executemany(
        """
        INSERT INTO interview_sessions (
            id, candidate_name, target_role, interview_type, status, overall_score, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "David Saputra", "Software Engineer", "technical", "draft", 0.0, "Prepare for backend and systems questions."),
            (2, "Nina Hartono", "Product Manager", "behavioral", "active", 0.0, "Focus on stakeholder communication and prioritisation."),
        ],
    )

    connection.executemany(
        """
        INSERT INTO interview_questions (
            id, session_id, category, question_text
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (1, 1, "technical", "Describe how you would design a scalable API for an application with high read traffic."),
            (2, 1, "behavioral", "Tell me about a time you handled ambiguity in a project."),
            (3, 2, "behavioral", "How do you align product trade-offs between engineering and business stakeholders?"),
        ],
    )

    connection.executemany(
        """
        INSERT INTO interview_responce (
            id, question_id, user_answer, ai_feedback, score, improvement_tips
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "I would use a stateless service, cache reads, and add observability around latency and throughput.", "Strong structure and good use of scaling principles.", 84.0, "Add explicit trade-offs and failure scenarios to deepen the answer."),
            (2, 3, "I usually frame decisions around customer impact and data, then document assumptions to align stakeholders.", "Good communication and prioritisation style.", 88.0, "Include a concrete example with a tough trade-off."),
        ],
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
