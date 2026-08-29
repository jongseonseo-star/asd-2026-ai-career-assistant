from pathlib import Path
import os
import sqlite3


# ---------------------------------------------------------
# Database configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "candidate_data.db"

DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# Database connection
# ---------------------------------------------------------

def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ---------------------------------------------------------
# Create database tables
# ---------------------------------------------------------

def create_tables(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            target_role TEXT NOT NULL,
            career_summary TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );


        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_profile_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0
                CHECK (is_primary IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (candidate_profile_id)
                REFERENCES candidate_profiles(id)
                ON DELETE CASCADE,

            UNIQUE (candidate_profile_id, title)
        );


        CREATE TABLE IF NOT EXISTS candidate_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_profile_id INTEGER NOT NULL,
            skill_name TEXT NOT NULL,

            proficiency_level TEXT NOT NULL
                CHECK (
                    proficiency_level IN (
                        'Beginner',
                        'Intermediate',
                        'Advanced',
                        'Expert'
                    )
                ),

            years_experience REAL NOT NULL DEFAULT 0
                CHECK (years_experience >= 0),

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (candidate_profile_id)
                REFERENCES candidate_profiles(id)
                ON DELETE CASCADE,

            UNIQUE (candidate_profile_id, skill_name)
        );


        CREATE INDEX IF NOT EXISTS idx_resumes_profile
        ON resumes(candidate_profile_id);


        CREATE INDEX IF NOT EXISTS idx_skills_profile
        ON candidate_skills(candidate_profile_id);
        """
    )


# ---------------------------------------------------------
# Seed CandidateProfile records
# ---------------------------------------------------------

def seed_profiles(connection):

    existing_count = connection.execute(
        "SELECT COUNT(*) FROM candidate_profiles"
    ).fetchone()[0]

    if existing_count > 0:
        return

    profiles = [
        (
            1,
            "Alex Morgan",
            "alex.morgan@example.com",
            "Software Engineer",
            "Computer science graduate interested in backend development and cloud systems.",
        ),
        (
            2,
            "Sofia Chen",
            "sofia.chen@example.com",
            "Data Analyst",
            "Graduate analyst with experience in Python, SQL, dashboards and data visualisation.",
        ),
        (
            3,
            "Daniel Kim",
            "daniel.kim@example.com",
            "DevOps Engineer",
            "Junior engineer interested in CI/CD, containers, automation and cloud infrastructure.",
        ),
        (
            4,
            "Maya Patel",
            "maya.patel@example.com",
            "UX Designer",
            "Design graduate focused on accessible interfaces, user research and prototyping.",
        ),
        (
            5,
            "Lucas Silva",
            "lucas.silva@example.com",
            "Frontend Developer",
            "Web developer experienced with HTML, CSS, JavaScript and responsive user interfaces.",
        ),
        (
            6,
            "Emma Wilson",
            "emma.wilson@example.com",
            "Business Analyst",
            "Business and technology graduate interested in requirements analysis and process improvement.",
        ),
        (
            7,
            "Noah Brown",
            "noah.brown@example.com",
            "Cybersecurity Analyst",
            "Entry-level security professional interested in secure systems and threat analysis.",
        ),
        (
            8,
            "Olivia Nguyen",
            "olivia.nguyen@example.com",
            "AI Engineer",
            "Software graduate interested in machine learning, local LLMs and AI-assisted applications.",
        ),
        (
            9,
            "Ethan Taylor",
            "ethan.taylor@example.com",
            "Cloud Engineer",
            "Graduate engineer developing skills in Docker, AWS, networking and infrastructure.",
        ),
        (
            10,
            "Grace Lee",
            "grace.lee@example.com",
            "Product Analyst",
            "Technology graduate interested in product analytics, experimentation and customer insights.",
        ),
    ]

    connection.executemany(
        """
        INSERT INTO candidate_profiles (
            id,
            full_name,
            email,
            target_role,
            career_summary
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        profiles,
    )


# ---------------------------------------------------------
# Seed Resume records
# ---------------------------------------------------------

def seed_resumes(connection):

    existing_count = connection.execute(
        "SELECT COUNT(*) FROM resumes"
    ).fetchone()[0]

    if existing_count > 0:
        return

    resumes = [
        (
            1,
            1,
            "Software Engineering Resume",
            "Computer science graduate with Python, Flask, Git, REST API and SQLite project experience.",
            1,
        ),
        (
            2,
            2,
            "Data Analyst Resume",
            "Graduate analyst with Python, SQL, Excel and dashboard development experience.",
            1,
        ),
        (
            3,
            3,
            "DevOps Resume",
            "Junior engineer with Docker, GitHub Actions, Linux and CI/CD project experience.",
            1,
        ),
        (
            4,
            4,
            "UX Design Resume",
            "UX design graduate with user research, wireframing, usability testing and Figma experience.",
            1,
        ),
        (
            5,
            5,
            "Frontend Development Resume",
            "Frontend developer with HTML, CSS, JavaScript and responsive web design experience.",
            1,
        ),
        (
            6,
            6,
            "Business Analyst Resume",
            "Graduate business analyst with requirements gathering, process modelling and documentation experience.",
            1,
        ),
        (
            7,
            7,
            "Cybersecurity Resume",
            "Security graduate with networking, vulnerability assessment and secure coding knowledge.",
            1,
        ),
        (
            8,
            8,
            "AI Engineering Resume",
            "Software graduate with Python, machine learning, Ollama and LLM application experience.",
            1,
        ),
        (
            9,
            9,
            "Cloud Engineering Resume",
            "Graduate engineer with Docker, AWS, Linux and cloud infrastructure project experience.",
            1,
        ),
        (
            10,
            10,
            "Product Analyst Resume",
            "Technology graduate with analytics, SQL, experimentation and product research experience.",
            1,
        ),
    ]

    connection.executemany(
        """
        INSERT INTO resumes (
            id,
            candidate_profile_id,
            title,
            content,
            is_primary
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        resumes,
    )


# ---------------------------------------------------------
# Seed CandidateSkill records
# ---------------------------------------------------------

def seed_skills(connection):

    existing_count = connection.execute(
        "SELECT COUNT(*) FROM candidate_skills"
    ).fetchone()[0]

    if existing_count > 0:
        return

    skills = [
        (1, 1, "Python", "Advanced", 2),
        (2, 1, "Flask", "Intermediate", 1),

        (3, 2, "SQL", "Advanced", 2),
        (4, 2, "Excel", "Advanced", 3),

        (5, 3, "Docker", "Advanced", 2),
        (6, 3, "GitHub Actions", "Intermediate", 1),

        (7, 4, "Figma", "Advanced", 2),
        (8, 4, "User Research", "Intermediate", 2),

        (9, 5, "JavaScript", "Advanced", 2),
        (10, 5, "CSS", "Advanced", 3),

        (11, 6, "Requirements Analysis", "Advanced", 2),
        (12, 6, "Process Modelling", "Intermediate", 1),

        (13, 7, "Network Security", "Intermediate", 1),
        (14, 7, "Secure Coding", "Intermediate", 1),

        (15, 8, "Machine Learning", "Intermediate", 1),
        (16, 8, "Ollama", "Intermediate", 1),

        (17, 9, "AWS", "Intermediate", 1),
        (18, 9, "Linux", "Advanced", 2),

        (19, 10, "Product Analytics", "Advanced", 2),
        (20, 10, "SQL", "Intermediate", 2),
    ]

    connection.executemany(
        """
        INSERT INTO candidate_skills (
            id,
            candidate_profile_id,
            skill_name,
            proficiency_level,
            years_experience
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        skills,
    )


# ---------------------------------------------------------
# Print database summary
# ---------------------------------------------------------

def print_summary(connection):

    tables = [
        ("CandidateProfile", "candidate_profiles"),
        ("Resume", "resumes"),
        ("CandidateSkill", "candidate_skills"),
    ]

    print(f"Database: {DB_PATH}")

    for label, table_name in tables:

        count = connection.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        print(f"{label}: {count} records")


# ---------------------------------------------------------
# Initialise database
# ---------------------------------------------------------

def initialise_database():

    connection = get_connection()

    try:

        create_tables(connection)

        seed_profiles(connection)
        seed_resumes(connection)
        seed_skills(connection)

        connection.commit()

        print_summary(connection)

    finally:

        connection.close()


# ---------------------------------------------------------
# Application entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    initialise_database()