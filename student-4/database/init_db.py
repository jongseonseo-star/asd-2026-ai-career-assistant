from __future__ import annotations

import sqlite3
from pathlib import Path


COMPANIES = [
    ("Atlassian", "Technology", "Sydney", "https://atlassian.com"),
    ("Canva", "Technology", "Sydney", "https://canva.com"),
    ("Commonwealth Bank", "Banking", "Sydney", "https://commbank.com.au"),
    ("Qantas", "Aviation", "Mascot", "https://qantas.com"),
    ("Telstra", "Telecommunications", "Melbourne", "https://telstra.com.au"),
    ("Woolworths Group", "Retail", "Bella Vista", "https://woolworthsgroup.com.au"),
    ("Macquarie Group", "Financial Services", "Sydney", "https://macquarie.com"),
    ("REA Group", "Technology", "Melbourne", "https://rea-group.com"),
    ("SafetyCulture", "Technology", "Sydney", "https://safetyculture.com"),
    ("WiseTech Global", "Logistics Technology", "Sydney", "https://wisetechglobal.com"),
]

JOBS = [
    (1, "Graduate Software Engineer", "Sydney", "Full-time", "Junior", "Build reliable cloud products with a collaborative engineering team.", 75000, 90000, "2026-09-20", "open"),
    (2, "Backend Engineer", "Sydney", "Full-time", "Mid", "Develop Python APIs and distributed services for a global design platform.", 110000, 140000, "2026-09-22", "open"),
    (3, "Data Analyst", "Sydney", "Full-time", "Junior", "Create actionable insights using SQL, Python and customer data.", 80000, 100000, "2026-09-18", "open"),
    (4, "DevOps Engineer", "Mascot", "Full-time", "Mid", "Improve CI/CD, observability and container platforms.", 115000, 145000, "2026-09-25", "open"),
    (5, "Cloud Support Associate", "Melbourne", "Full-time", "Junior", "Support cloud systems and automate operational tasks.", 70000, 88000, "2026-09-28", "open"),
    (6, "Frontend Developer", "Sydney", "Contract", "Mid", "Deliver accessible customer experiences using modern web technologies.", 105000, 130000, "2026-09-16", "open"),
    (7, "Cyber Security Analyst", "Sydney", "Full-time", "Junior", "Monitor security events and improve risk controls.", 85000, 105000, "2026-10-01", "open"),
    (8, "Machine Learning Engineer", "Melbourne", "Full-time", "Mid", "Productionise recommendation models and data pipelines.", 125000, 155000, "2026-09-30", "open"),
    (9, "Product Support Engineer", "Sydney", "Full-time", "Junior", "Solve technical customer problems and improve support tooling.", 78000, 98000, "2026-09-21", "open"),
    (10, "Software Test Engineer", "Sydney", "Full-time", "Mid", "Build automated API and user-interface test suites.", 95000, 120000, "2026-09-27", "open"),
]

SKILLS = [
    (1, "Python", "required"), (1, "Git", "required"),
    (2, "Python", "required"), (2, "Flask", "preferred"),
    (3, "SQL", "required"), (3, "Power BI", "preferred"),
    (4, "Docker", "required"), (4, "GitHub Actions", "required"),
    (5, "Linux", "required"), (5, "AWS", "preferred"),
    (6, "JavaScript", "required"), (6, "HTMX", "preferred"),
    (7, "SIEM", "required"), (7, "Python", "preferred"),
    (8, "Machine Learning", "required"), (8, "Python", "required"),
    (9, "REST APIs", "required"), (9, "Troubleshooting", "required"),
    (10, "Pytest", "required"), (10, "Playwright", "preferred"),
]


def initialise_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                industry TEXT NOT NULL,
                location TEXT NOT NULL,
                website TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS job_postings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                location TEXT NOT NULL,
                employment_type TEXT NOT NULL,
                experience_level TEXT NOT NULL,
                description TEXT NOT NULL,
                salary_min INTEGER,
                salary_max INTEGER,
                closing_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS job_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_posting_id INTEGER NOT NULL,
                skill_name TEXT NOT NULL,
                importance TEXT NOT NULL DEFAULT 'required',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_posting_id) REFERENCES job_postings(id) ON DELETE CASCADE,
                UNIQUE(job_posting_id, skill_name)
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO companies(name, industry, location, website) VALUES (?, ?, ?, ?)",
                COMPANIES,
            )
        if connection.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] == 0:
            connection.executemany(
                """INSERT INTO job_postings(
                    company_id, title, location, employment_type, experience_level,
                    description, salary_min, salary_max, closing_date, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                JOBS,
            )
        if connection.execute("SELECT COUNT(*) FROM job_skills").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO job_skills(job_posting_id, skill_name, importance) VALUES (?, ?, ?)",
                SKILLS,
            )


if __name__ == "__main__":
    initialise_database(Path("data/jobs.db"))
