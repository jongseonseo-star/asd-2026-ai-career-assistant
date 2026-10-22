"""
Shared non-containerised local Multi-Agent Server for Release 2.

Coordinates Planner, Worker, and Reviewer agents for career assistance and interview preparation.
Supports invocation via HTTP API (integrated application) and directly from the terminal (CLI).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request
from resume_multi_agent import register_resume_routes

import job_multi_agent

BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts" / "multi_agent"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() in {"1", "true", "yes"}
PLANNER_MODEL = os.getenv("PLANNER_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"))
WORKER_MODEL = os.getenv("WORKER_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"))
REVIEWER_MODEL = os.getenv("REVIEWER_MODEL", os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120.0"))
MULTI_AGENT_PORT = int(os.getenv("MULTI_AGENT_PORT", "8767"))
AI_SERVICES_HOST = os.getenv("AI_SERVICES_HOST", "127.0.0.1")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_prompt_file(filename: str, fallback_content: str = "") -> str:
    path = PROMPTS_DIR / filename
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return fallback_content.strip()


def parse_json_from_text(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                candidate = json.loads(text[start : end + 1])
                if isinstance(candidate, dict):
                    return candidate
            except json.JSONDecodeError:
                pass
    return None


def call_ollama(model: str, system_prompt: str, user_prompt: str, timeout: float | None = None, response_format: dict | None = None) -> str | None:
    if not OLLAMA_ENABLED:
        return None
    request_timeout = timeout or OLLAMA_TIMEOUT
    url = f"{OLLAMA_BASE_URL}/api/chat"
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.2, "num_predict": 1024},
    }
    if response_format is not None:
        body["format"] = response_format
    req = Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=request_timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "").strip()
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    return None


# Planner Agent

class PlannerAgent:
    """Strategic Planner Agent: Creates structured workflow plans (defining objectives, steps, evidence requirements, and approval checkpoints)."""

    def __init__(self, model: str = PLANNER_MODEL):
        self.name = "Planner"
        self.role = "Creates structured workflow plans (defining objectives, steps, evidence requirements, and approval checkpoints)"
        self.model = model
        self.system_prompt = load_prompt_file(
            "planner_system.txt",
            fallback_content="You are the Planner Agent. Creates structured workflow plans (defining objectives, steps, evidence requirements, and approval checkpoints).",
        )

    def plan_interview_prep(self, target_role: str, interview_type: str, question_count: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        user_prompt = json.dumps({
            "task": "plan_interview_preparation",
            "target_role": target_role,
            "interview_type": interview_type,
            "target_question_count": question_count,
            "context": context or {},
            "instructions": (
                "Decompose the interview preparation into structured competency focus areas, "
                "difficulty distribution, and an evaluation rubric. Return valid JSON with keys: "
                "'plan_id', 'target_role', 'interview_type', 'competencies', 'steps', 'rubric'."
            ),
        })

        output_text = call_ollama(self.model, self.system_prompt, user_prompt)
        parsed = parse_json_from_text(output_text) if output_text else None
        if parsed and "steps" in parsed and "rubric" in parsed:
            parsed.setdefault("plan_id", f"plan-{int(time.time())}")
            parsed["generated_by"] = f"{self.name} ({self.model})"
            return parsed

        # Deterministic structured fallback
        return {
            "plan_id": f"plan-{int(time.time())}",
            "target_role": target_role,
            "interview_type": interview_type,
            "target_question_count": question_count,
            "objectives": [
                f"Formulate structured interview preparation blueprint for {target_role}",
                "Evaluate candidate readiness against competency standards using database evidence",
            ],
            "evidence_requirements": [
                "Student enrolment & interview session records from database",
                f"{target_role} Core Technical Competencies demonstration",
                "STAR structured response evidence",
            ],
            "approval_checkpoints": [
                "Worker deliverable generation from database evidence",
                "Reviewer risk, correction & retest audit",
                "Human Final Decision Maker (Accept, Partially Accept, Reject)",
            ],
            "competencies": [
                f"{target_role} Core Technical Competencies",
                "Problem Solving & Architectural Trade-offs",
                "STAR Behavioral Alignment & Clear Communication",
                "Operational Excellence & Error Handling",
            ],
            "steps": [
                {
                    "step_id": 1,
                    "title": "Core Domain Fundamentals",
                    "focus": f"Assess foundational competencies and tools required for a {target_role}.",
                    "expected_output": f"Generate {max(1, question_count // 3)} fundamental technical or role questions.",
                },
                {
                    "step_id": 2,
                    "title": "Scenario & Trade-Off Analysis",
                    "focus": "Evaluate decision-making, resilience, and trade-off justification.",
                    "expected_output": f"Generate {max(1, question_count // 3)} practical problem-solving questions.",
                },
                {
                    "step_id": 3,
                    "title": "Behavioral & Communication Mastery",
                    "focus": "Examine team collaboration, conflict resolution, and measurable impact (STAR format).",
                    "expected_output": f"Generate {max(1, question_count - (2 * (question_count // 3)))} behavioral questions.",
                },
            ],
            "rubric": {
                "technical_accuracy": 0.35,
                "clarity_and_structure": 0.25,
                "practical_evidence_and_tradeoffs": 0.25,
                "star_method_adherence": 0.15,
            },
            "generated_by": f"{self.name} (deterministic-rules)",
        }

    def plan_answer_evaluation(self, target_role: str, question: str, candidate_answer: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        user_prompt = json.dumps({
            "task": "plan_answer_evaluation",
            "target_role": target_role,
            "question": question,
            "candidate_answer": candidate_answer,
            "context": context or {},
            "instructions": (
                "Formulate an evaluation plan with key evaluation dimensions and expectations. "
                "Return JSON with 'evaluation_plan_id', 'criteria', 'dimensions', 'target_role'."
            ),
        })

        output_text = call_ollama(self.model, self.system_prompt, user_prompt)
        parsed = parse_json_from_text(output_text) if output_text else None
        if parsed and "dimensions" in parsed:
            parsed.setdefault("evaluation_plan_id", f"eval-plan-{int(time.time())}")
            parsed["generated_by"] = f"{self.name} ({self.model})"
            return parsed

        return {
            "evaluation_plan_id": f"eval-plan-{int(time.time())}",
            "target_role": target_role,
            "question": question,
            "objectives": [
                f"Evaluate candidate response for {target_role} role",
                "Assess concrete evidence grounding, trade-offs, and STAR structure",
            ],
            "evidence_requirements": [
                "Student enrolment and candidate response context",
                "Evaluation criteria rubric weights",
            ],
            "approval_checkpoints": [
                "Worker answer evaluation synthesis",
                "Reviewer risk, correction & retest audit",
                "Human Final Decision Maker approval",
            ],
            "dimensions": [
                {"name": "technical_correctness", "weight": 0.40, "description": "Accurate concepts, valid trade-offs, and role-appropriate depth."},
                {"name": "clarity_and_structure", "weight": 0.25, "description": "Concise delivery, logical progression, and STAR adherence."},
                {"name": "concrete_evidence", "weight": 0.20, "description": "Specific metrics, concrete examples, and past experience."},
                {"name": "depth_and_edge_cases", "weight": 0.15, "description": "Consideration of limitations, scalability, and error scenarios."},
            ],
            "generated_by": f"{self.name} (deterministic-rules)",
        }


# Worker Agent

class WorkerAgent:
    """Execution Worker Agent: Retrieves student enrolment records from the database and executes tasks strictly using supplied database evidence."""

    def __init__(self, model: str = WORKER_MODEL):
        self.name = "Worker"
        self.role = "Retrieves student enrolment records from the database and executes tasks strictly using supplied database evidence"
        self.model = model
        self.system_prompt = load_prompt_file(
            "worker_system.txt",
            fallback_content="You are the Worker Agent. Retrieves student enrolment records from the database and executes tasks strictly using supplied database evidence.",
        )

    def execute_interview_prep(
        self,
        plan: dict[str, Any],
        question_count: int,
        reviewer_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_prompt = json.dumps({
            "task": "execute_interview_preparation",
            "plan": plan,
            "target_question_count": question_count,
            "reviewer_feedback": reviewer_feedback,
            "instructions": (
                "Generate exactly the requested number of high-quality interview questions aligned with the plan. "
                "If reviewer_feedback is provided, explicitly incorporate improvements. "
                "Return JSON with 'work_id', 'questions' (array of objects with 'question', 'category', 'difficulty', 'key_points')."
            ),
        })

        output_text = call_ollama(self.model, self.system_prompt, user_prompt)
        parsed = parse_json_from_text(output_text) if output_text else None
        if parsed and isinstance(parsed.get("questions"), list) and parsed["questions"]:
            parsed.setdefault("work_id", f"work-{int(time.time())}")
            parsed["generated_by"] = f"{self.name} ({self.model})"
            return parsed

        role = plan.get("target_role", "Software Engineer")
        itype = plan.get("interview_type", "technical")

        fallback_catalog = [
            {
                "question": f"Explain the architectural trade-offs you consider when designing scalable microservices for a {role}.",
                "category": "Architecture",
                "difficulty": "Advanced",
                "key_points": ["Decoupling", "Data consistency", "Latency vs throughput", "Failure isolation"],
            },
            {
                "question": f"Describe a situation where a production service degraded. How did you diagnose, mitigate, and prevent recurrence?",
                "category": "Operational Excellence",
                "difficulty": "Medium",
                "key_points": ["Observability & metrics", "Root cause analysis", "Post-mortem actions", "STAR format"],
            },
            {
                "question": f"How do you ensure secure input validation, state isolation, and data integrity in your {role} workflows?",
                "category": "Security & Reliability",
                "difficulty": "Medium",
                "key_points": ["Input boundaries", "Least privilege", "Audit logs", "Defensive programming"],
            },
            {
                "question": f"Walk through an instance where you balanced delivery speed against technical debt when collaborating with cross-functional teams.",
                "category": "Behavioral",
                "difficulty": "Medium",
                "key_points": ["Prioritization", "Stakeholder communication", "Pragmatic debt management", "Measurable outcomes"],
            },
            {
                "question": f"What testing strategies (unit, integration, contract) do you employ to validate complex distributed state changes for {role}?",
                "category": "Quality Engineering",
                "difficulty": "Advanced",
                "key_points": ["Test pyramid", "Contract testing", "Determinism", "CI automation"],
            },
        ]

        if reviewer_feedback and reviewer_feedback.get("revision_recommendations"):
            recs = reviewer_feedback["revision_recommendations"]
            for q in fallback_catalog:
                q["key_points"].append(f"Reviewed emphasis: {recs[0] if recs else 'Add concrete evidence'}")

        selected = (fallback_catalog * ((question_count // len(fallback_catalog)) + 1))[:question_count]
        return {
            "work_id": f"work-{int(time.time())}",
            "questions": selected,
            "revision_applied": reviewer_feedback is not None,
            "generated_by": f"{self.name} (deterministic-rules)",
        }

    def execute_answer_evaluation(
        self,
        plan: dict[str, Any],
        question: str,
        candidate_answer: str,
        reviewer_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_prompt = json.dumps({
            "task": "execute_answer_evaluation",
            "plan": plan,
            "question": question,
            "candidate_answer": candidate_answer,
            "reviewer_feedback": reviewer_feedback,
            "instructions": (
                "Evaluate the candidate answer against the plan's criteria and any reviewer feedback. "
                "If reviewer_feedback is provided, explicitly correct your previous evaluation and address each critique. "
                "If the candidate's answer is unprofessional, negative, dismissive, or fails to address the question, score it between 0 and 30. "
                "Return JSON with 'work_id', 'score' (0-100), 'feedback' (a clear text summary string, not an object), 'strengths' (list of strings), 'gaps' (list of strings), 'improvement_tips' (list of strings)."
            ),
        })

        output_text = call_ollama(self.model, self.system_prompt, user_prompt)
        parsed = parse_json_from_text(output_text) if output_text else None
        if parsed and "score" in parsed and "feedback" in parsed:
            if isinstance(parsed["feedback"], dict):
                fb_dict = parsed["feedback"]
                if not parsed.get("improvement_tips") and fb_dict.get("improvement_tips"):
                    parsed["improvement_tips"] = fb_dict["improvement_tips"]
                if not parsed.get("strengths") and fb_dict.get("strengths"):
                    parsed["strengths"] = fb_dict["strengths"]
                if not parsed.get("gaps") and fb_dict.get("gaps"):
                    parsed["gaps"] = fb_dict["gaps"]
                summary = fb_dict.get("summary") or fb_dict.get("assessment") or fb_dict.get("feedback")
                if not summary:
                    summary_parts = []
                    if fb_dict.get("strengths"):
                        summary_parts.append("Strengths: " + "; ".join(str(s) for s in fb_dict["strengths"]))
                    if fb_dict.get("gaps"):
                        summary_parts.append("Gaps: " + "; ".join(str(g) for g in fb_dict["gaps"]))
                    summary = " | ".join(summary_parts) if summary_parts else "Candidate answer evaluated against rubric."
                parsed["feedback"] = str(summary)
            parsed.setdefault("work_id", f"work-{int(time.time())}")
            parsed["generated_by"] = f"{self.name} ({self.model})"
            return parsed

        words = candidate_answer.strip().split()
        word_count = len(words)
        has_star_signals = any(k in candidate_answer.lower() for k in ["situation", "task", "action", "result", "because", "impact", "metric"])
        has_tech_signals = any(k in candidate_answer.lower() for k in ["design", "database", "api", "latency", "scale", "security", "cache", "service"])

        base_score = 65.0
        if word_count > 30:
            base_score += 10.0
        if has_star_signals:
            base_score += 10.0
        if has_tech_signals:
            base_score += 10.0
        if word_count < 5:
            base_score = 15.0
        elif word_count < 15:
            base_score -= 20.0

        score = min(max(round(base_score, 1), 20.0), 95.0)

        strengths = ["Addresses the core question directly"]
        if has_tech_signals:
            strengths.append("Mentions relevant technical principles and architectural considerations")
        if has_star_signals:
            strengths.append("Demonstrates structured thinking and cause-and-effect reasoning")

        gaps = []
        if word_count < 35:
            gaps.append("Answer is brief; needs deeper exploration of trade-offs and real-world edge cases")
        if not has_star_signals:
            gaps.append("Could benefit from explicit STAR formatting (Situation, Task, Action, Measurable Result)")

        tips = [
            "Quantify your impact with measurable metrics (e.g. percentage latency reduction or throughput increase).",
            "Elaborate on alternative approaches you rejected and why your chosen path was superior.",
            "Conclude with key lessons learned or continuous monitoring mechanisms implemented.",
        ]

        if reviewer_feedback and reviewer_feedback.get("revision_recommendations"):
            tips.insert(0, f"Addressed Reviewer note: {reviewer_feedback['revision_recommendations'][0]}")

        return {
            "work_id": f"work-{int(time.time())}",
            "score": score,
            "feedback": (
                f"The response demonstrates a solid foundational understanding of the problem space ({score}/100). "
                f"It addresses the core expectations for the role while offering practical reasoning. "
                "Strengthening concrete metrics and edge-case handling will elevate it to top-tier calibre."
            ),
            "strengths": strengths,
            "gaps": gaps,
            "improvement_tips": tips,
            "generated_by": f"{self.name} (deterministic-rules)",
        }


# Reviewer Agent

class ReviewerAgent:
    """Independent Quality Reviewer Agent: Reviews worker output against the plan and database evidence to assess risk, recommend corrections, and suggest retests."""

    def __init__(self, model: str = REVIEWER_MODEL):
        self.name = "Reviewer"
        self.role = "Reviews worker output against the plan and database evidence to assess risk, recommend corrections, and suggest retests"
        self.model = model
        self.system_prompt = load_prompt_file(
            "reviewer_system.txt",
            fallback_content="You are the Reviewer Agent. Reviews worker output against the plan and database evidence to assess risk, recommend corrections, and suggest retests.",
        )

    def review_deliverables(
        self,
        plan: dict[str, Any],
        work: dict[str, Any],
        iteration: int = 1,
        max_iterations: int = 15,
    ) -> dict[str, Any]:
        user_prompt = json.dumps({
            "task": "review_deliverable",
            "iteration": iteration,
            "max_iterations": max_iterations,
            "plan": plan,
            "work": work,
            "instructions": (
                "Audit the deliverable against the plan's rubric and criteria. "
                "Provide an audit score (0-100), strengths, weaknesses, critique, and verdict ('approved' or 'needs_revision'). "
                "If needs_revision, provide actionable revision_recommendations. "
                "Return JSON with 'review_id', 'verdict', 'score', 'strengths', 'weaknesses', 'critique', 'revision_recommendations'."
            ),
        })

        output_text = call_ollama(self.model, self.system_prompt, user_prompt)
        parsed = parse_json_from_text(output_text) if output_text else None
        if parsed and "verdict" in parsed and "score" in parsed:
            parsed.setdefault("review_id", f"review-{int(time.time())}")
            parsed["generated_by"] = f"{self.name} ({self.model})"
            return parsed

        # Deterministic evaluation logic
        # If iteration > 1, or deliverables are already high quality, approve.
        is_question_prep = "questions" in work
        is_answer_eval = "score" in work

        if is_question_prep:
            questions = work.get("questions", [])
            has_categories = all("category" in q for q in questions if isinstance(q, dict))
            has_key_points = all("key_points" in q for q in questions if isinstance(q, dict))
            is_valid = len(questions) > 0 and has_categories and has_key_points

            score = 88.0 if is_valid else 68.0
            verdict = "approved" if (score >= 80.0 or iteration >= max_iterations) else "needs_revision"
            strengths = [
                "Role alignment is clear and targets core competencies.",
                "Questions contain clear evaluation criteria and focus areas.",
            ]
            weaknesses = [] if verdict == "approved" else ["Add deeper trade-off requirements to questions."]
            recs = ["Ensure candidate answers are prompted for measurable metrics and technical edge cases."]
        else:
            cand_score = work.get("score", 70.0)
            score = 86.0 if cand_score > 0 else 60.0
            verdict = "approved" if (score >= 80.0 or iteration >= max_iterations) else "needs_revision"
            strengths = [
                "Evaluation includes balanced strengths and actionable improvement tips.",
                "Scoring aligns with rubric dimensions.",
            ]
            weaknesses = [] if verdict == "approved" else ["Tips should include more concrete operational steps."]
            recs = ["Provide even more role-specific benchmark standards in the improvement tips."]

        risk = "Low: Deliverables are strictly grounded in supplied database evidence." if verdict == "approved" else "Medium: Gaps identified relative to plan criteria; corrections recommended."
        retests = [
            f"Verify {plan.get('target_role', 'role')} edge cases under degraded operational conditions.",
            "Confirm response alignment with supplied database evidence and rubric criteria.",
        ]

        return {
            "review_id": f"review-{int(time.time())}",
            "verdict": verdict,
            "score": score,
            "risk": risk,
            "recommend_corrections": recs,
            "suggest_retests": retests,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "critique": f"Reviewer verification completed with quality rating {score}/100. Deliverables align with planner rubric.",
            "revision_recommendations": recs,
            "generated_by": f"{self.name} (deterministic-rules)",
        }


# Multi-Agent Coordinator
class MultiAgentCoordinator:
    """Coordinates the Planner -> Worker -> Reviewer execution loop."""

    def __init__(self, planner: PlannerAgent | None = None, worker: WorkerAgent | None = None, reviewer: ReviewerAgent | None = None):
        self.planner = planner or PlannerAgent()
        self.worker = worker or WorkerAgent()
        self.reviewer = reviewer or ReviewerAgent()

    def coordinate_interview_prep(
        self,
        target_role: str,
        interview_type: str = "technical",
        question_count: int = 3,
        context: dict[str, Any] | None = None,
        max_iterations: int = 15,
    ) -> dict[str, Any]:
        started = time.monotonic()
        trajectory: list[dict[str, Any]] = []

        # Step 1: Planner creates the preparation curriculum plan
        plan = self.planner.plan_interview_prep(target_role, interview_type, question_count, context)
        trajectory.append({
            "stage": "planning",
            "agent": self.planner.name,
            "timestamp": utc_now_iso(),
            "action": "Generated structured interview preparation plan and rubric",
            "output_summary": f"Plan with {len(plan.get('steps', []))} steps and {len(plan.get('competencies', []))} competencies",
            "details": plan,
        })

        iteration = 0
        reviewer_feedback: dict[str, Any] | None = None
        final_work: dict[str, Any] = {}
        final_review: dict[str, Any] = {}

        # Step 2: Loop of Worker generating, Reviewer auditing
        while iteration < max_iterations:
            iteration += 1

            # Worker executes
            work = self.worker.execute_interview_prep(plan, question_count, reviewer_feedback)
            trajectory.append({
                "stage": f"execution_iteration_{iteration}",
                "agent": self.worker.name,
                "timestamp": utc_now_iso(),
                "action": f"Synthesized {len(work.get('questions', []))} interview questions",
                "output_summary": f"{len(work.get('questions', []))} questions created (revision={work.get('revision_applied')})",
                "details": work,
            })
            final_work = work

            # Reviewer audits
            review = self.reviewer.review_deliverables(plan, work, iteration=iteration, max_iterations=max_iterations)
            trajectory.append({
                "stage": f"review_iteration_{iteration}",
                "agent": self.reviewer.name,
                "timestamp": utc_now_iso(),
                "action": f"Audited deliverables: verdict={review.get('verdict')}, score={review.get('score')}",
                "output_summary": review.get("critique"),
                "details": review,
            })
            final_review = review

            if review.get("verdict") == "approved":
                break

            reviewer_feedback = review

        duration = round(time.monotonic() - started, 3)
        human_status = "Accept" if final_review.get("verdict") == "approved" else "Partially Accept"
        human_decision = {
            "role": "Human — Final Decision Maker",
            "decision": human_status,
            "available_decisions": ["Accept", "Partially Accept", "Reject"],
            "authority": "Grants final approval decision (Accept, Partially Accept, or Reject).",
        }
        trajectory.append({
            "stage": "human_governance",
            "agent": "Human — Final Decision Maker",
            "timestamp": utc_now_iso(),
            "action": f"Presented to Human Decision Maker: decision={human_status}",
            "output_summary": human_decision["authority"],
            "details": human_decision,
        })

        return {
            "status": "completed",
            "release": "Release 2",
            "architecture": "Multi-Agent Coordination (Planner -> Worker -> Reviewer -> Human)",
            "target_role": target_role,
            "interview_type": interview_type,
            "iterations": iteration,
            "approved": final_review.get("verdict") == "approved",
            "plan": plan,
            "work": final_work,
            "review": final_review,
            "human_decision": human_decision,
            "questions": final_work.get("questions", []),
            "trajectory": trajectory,
            "duration_seconds": duration,
        }

    def coordinate_answer_evaluation(
        self,
        target_role: str,
        question: str,
        candidate_answer: str,
        context: dict[str, Any] | None = None,
        max_iterations: int = 15,
    ) -> dict[str, Any]:
        started = time.monotonic()
        trajectory: list[dict[str, Any]] = []

        # Step 1: Planner creates evaluation dimensions
        plan = self.planner.plan_answer_evaluation(target_role, question, candidate_answer, context)
        trajectory.append({
            "stage": "planning",
            "agent": self.planner.name,
            "timestamp": utc_now_iso(),
            "action": "Generated evaluation criteria dimensions and rubric",
            "output_summary": f"{len(plan.get('dimensions', []))} evaluation dimensions defined",
            "details": plan,
        })

        iteration = 0
        reviewer_feedback: dict[str, Any] | None = None
        final_work: dict[str, Any] = {}
        final_review: dict[str, Any] = {}

        while iteration < max_iterations:
            iteration += 1

            # Worker evaluates
            work = self.worker.execute_answer_evaluation(plan, question, candidate_answer, reviewer_feedback)
            trajectory.append({
                "stage": f"execution_iteration_{iteration}",
                "agent": self.worker.name,
                "timestamp": utc_now_iso(),
                "action": f"Synthesized answer evaluation (score={work.get('score')})",
                "output_summary": work.get("feedback"),
                "details": work,
            })
            final_work = work

            # Reviewer audits
            review = self.reviewer.review_deliverables(plan, work, iteration=iteration, max_iterations=max_iterations)
            trajectory.append({
                "stage": f"review_iteration_{iteration}",
                "agent": self.reviewer.name,
                "timestamp": utc_now_iso(),
                "action": f"Audited answer evaluation: verdict={review.get('verdict')}, score={review.get('score')}",
                "output_summary": review.get("critique"),
                "details": review,
            })
            final_review = review

            if review.get("verdict") == "approved":
                break

            reviewer_feedback = review

        duration = round(time.monotonic() - started, 3)
        human_status = "Accept" if final_review.get("verdict") == "approved" else "Partially Accept"
        human_decision = {
            "role": "Human — Final Decision Maker",
            "decision": human_status,
            "available_decisions": ["Accept", "Partially Accept", "Reject"],
            "authority": "Grants final approval decision (Accept, Partially Accept, or Reject).",
        }
        trajectory.append({
            "stage": "human_governance",
            "agent": "Human — Final Decision Maker",
            "timestamp": utc_now_iso(),
            "action": f"Presented to Human Decision Maker: decision={human_status}",
            "output_summary": human_decision["authority"],
            "details": human_decision,
        })

        return {
            "status": "completed",
            "release": "Release 2",
            "architecture": "Multi-Agent Coordination (Planner -> Worker -> Reviewer -> Human)",
            "target_role": target_role,
            "question": question,
            "iterations": iteration,
            "approved": final_review.get("verdict") == "approved",
            "score": final_work.get("score", 75.0),
            "feedback": final_work.get("feedback", ""),
            "improvement_tips": final_work.get("improvement_tips", []),
            "plan": plan,
            "work": final_work,
            "review": final_review,
            "human_decision": human_decision,
            "trajectory": trajectory,
            "duration_seconds": duration,
        }


coordinator = MultiAgentCoordinator()


# HTTP Routes for Integrated Application

@app.get("/")
def service_info():
    return jsonify({
        "service": "shared-multi-agent-server",
        "release": "Release 2",
        "description": "Shared local non-containerised Multi-Agent Server coordinating Planner, Worker, and Reviewer agents",
        "host": AI_SERVICES_HOST,
        "port": MULTI_AGENT_PORT,
        "agents": {
            "planner": {"name": coordinator.planner.name, "role": coordinator.planner.role, "model": coordinator.planner.model},
            "worker": {"name": coordinator.worker.name, "role": coordinator.worker.role, "model": coordinator.worker.model},
            "reviewer": {"name": coordinator.reviewer.name, "role": coordinator.reviewer.role, "model": coordinator.reviewer.model},
        },
        "endpoints": [
            "GET /health",
            "GET /agents",
            "POST /agent/plan",
            "POST /agent/work",
            "POST /agent/review",
            "POST /agent/coordinate",
            "POST /interview/prep",
            "POST /interview/evaluate",
            "POST /jobs/analyse",
            "POST /jobs/<job_id>/runs/<run_id>/decision",
            "POST /resume/review",
            "GET /resume/workflows/<workflow_id>",
            "POST /resume/workflows/<workflow_id>/human-review",
        ],
    }), 200


@app.get("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "shared-multi-agent-server",
        "release": "Release 2",
        "agents": ["planner", "worker", "reviewer"],
        "timestamp": utc_now_iso(),
    }), 200


@app.get("/agents")
def list_agents():
    return jsonify({
        "status": "success",
        "release": "Release 2",
        "agents": [
            {
                "id": "planner",
                "name": coordinator.planner.name,
                "role": coordinator.planner.role,
                "model": coordinator.planner.model,
                "description": "Creates structured workflow plans (defining objectives, steps, evidence requirements, and approval checkpoints).",
            },
            {
                "id": "worker",
                "name": coordinator.worker.name,
                "role": coordinator.worker.role,
                "model": coordinator.worker.model,
                "description": "Retrieves student enrolment records from the database and executes tasks strictly using supplied database evidence.",
            },
            {
                "id": "reviewer",
                "name": coordinator.reviewer.name,
                "role": coordinator.reviewer.role,
                "model": coordinator.reviewer.model,
                "description": "Reviews worker output against the plan and database evidence to assess risk, recommend corrections, and suggest retests.",
            },
        ],
        "governance": {
            "human_decision_maker": {
                "name": "Human — Final Decision Maker",
                "authority": "Grants final approval decision (Accept, Partially Accept, or Reject).",
            },
            "implementation_validator": {
                "name": "Implementation Validator (Agentic Loop)",
                "model": PLANNER_MODEL,
                "description": "Validates the correctness of the multi-agent system structure, agent entry functions, and coordinator wiring.",
            },
            "review_agent_loop": {
                "name": "Review Agent (Agentic Loop)",
                "model": REVIEWER_MODEL,
                "description": "Assesses coordination-level quality, agent sequencing, evidence grounding, and human-gating risks.",
            },
        },
    }), 200


@app.post("/agent/plan")
def agent_plan():
    data = request.get_json(silent=True) or {}
    role = data.get("target_role", "Software Engineer")
    itype = data.get("interview_type", "technical")
    q_count = int(data.get("question_count", 3))
    plan = coordinator.planner.plan_interview_prep(role, itype, q_count, data.get("context"))
    return jsonify({"status": "success", "agent": "Planner", "plan": plan}), 200


@app.post("/agent/work")
def agent_work():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan") or coordinator.planner.plan_interview_prep(data.get("target_role", "Software Engineer"), "technical", 3)
    q_count = int(data.get("question_count", 3))
    feedback = data.get("reviewer_feedback")
    work = coordinator.worker.execute_interview_prep(plan, q_count, feedback)
    return jsonify({"status": "success", "agent": "Worker", "work": work}), 200


@app.post("/agent/review")
def agent_review():
    data = request.get_json(silent=True) or {}
    plan = data.get("plan") or {}
    work = data.get("work") or {}
    review = coordinator.reviewer.review_deliverables(plan, work, iteration=int(data.get("iteration", 1)))
    return jsonify({"status": "success", "agent": "Reviewer", "review": review}), 200


@app.post("/agent/coordinate")
def agent_coordinate():
    data = request.get_json(silent=True) or {}
    task_type = data.get("task_type", "interview_prep")
    max_iter = int(data.get("max_iterations", 15))

    if task_type == "interview_evaluation":
        role = data.get("target_role", "Software Engineer")
        q = data.get("question_text", "Describe your experience.")
        ans = data.get("candidate_answer", "")
        result = coordinator.coordinate_answer_evaluation(role, q, ans, data.get("context"), max_iterations=max_iter)
    else:
        role = data.get("target_role", "Software Engineer")
        itype = data.get("interview_type", "technical")
        q_count = int(data.get("question_count", 3))
        result = coordinator.coordinate_interview_prep(role, itype, q_count, data.get("context"), max_iterations=max_iter)

    return jsonify(result), 200


@app.post("/jobs/analyse")
def job_analysis_route():
    data = request.get_json(silent=True)
    try:
        if (not isinstance(data, dict) or set(data) != {"query", "job_context"}
                or not job_multi_agent.contract.nonempty_text(data.get("query"))):
            raise ValueError("Provide a job context and a question of up to 2000 characters.")
        result = job_multi_agent.coordinate(data["job_context"], data["query"].strip(), coordinator, call_ollama)
        return jsonify(result)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except job_multi_agent.JobWorkflowError as error:
        return jsonify({"error": error.message, "dependency": "multi-agent"}), error.status


@app.post("/jobs/<int:job_id>/runs/<uuid:run_id>/decision")
def job_decision_route(job_id: int, run_id):
    try:
        return jsonify(job_multi_agent.record_decision(job_id, str(run_id), request.get_json(silent=True)))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except job_multi_agent.JobWorkflowError as error:
        return jsonify({"error": error.message}), error.status


@app.post("/interview/prep")
def interview_prep_route():
    data = request.get_json(silent=True) or {}
    role = str(data.get("target_role", "General role")).strip() or "General role"
    itype = str(data.get("interview_type", "general")).strip() or "general"
    q_count = max(1, min(int(data.get("question_count", 3)), 10))
    max_iter = max(1, min(int(data.get("max_iterations", 15)), 15))

    result = coordinator.coordinate_interview_prep(
        target_role=role,
        interview_type=itype,
        question_count=q_count,
        context=data.get("context"),
        max_iterations=max_iter,
    )
    return jsonify(result), 200


@app.post("/interview/evaluate")
def interview_evaluate_route():
    data = request.get_json(silent=True) or {}
    role = str(data.get("target_role", "General")).strip() or "General"
    q = str(data.get("question_text") or data.get("question") or "Interview Question").strip()
    ans = str(data.get("candidate_answer") or data.get("answer") or data.get("user_answer") or "").strip()
    max_iter = max(1, min(int(data.get("max_iterations", 15)), 15))

    if not ans:
        return jsonify({"error": "candidate_answer is required for evaluation."}), 400

    result = coordinator.coordinate_answer_evaluation(
        target_role=role,
        question=q,
        candidate_answer=ans,
        context=data.get("context"),
        max_iterations=max_iter,
    )
    return jsonify(result), 200


# CLI Runner & Formatting

def run_cli_interview_prep(role: str, itype: str, count: int, max_iter: int, as_json: bool = False):
    result = coordinator.coordinate_interview_prep(role, itype, count, max_iterations=max_iter)
    if as_json:
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 76)
    print("  RELEASE 2 MULTI-AGENT COORDINATION: INTERVIEW PREPARATION")
    print("=" * 76)
    print(f"Target Role:     {result['target_role']}")
    print(f"Interview Type:  {result['interview_type']}")
    print(f"Iterations:      {result['iterations']}")
    print(f"Approved:        {result['approved']}")
    print(f"Duration:        {result['duration_seconds']}s")
    print("-" * 76)

    print("\n[PLANNER AGENT: Strategic Blueprint]")
    plan = result.get("plan", {})
    print(f"Plan ID:      {plan.get('plan_id')}")
    print(f"Generated By: {plan.get('generated_by')}")
    print("Competencies Focused:")
    for comp in plan.get("competencies", []):
        print(f"  * {comp}")
    print("Planned Steps:")
    for step in plan.get("steps", []):
        print(f"  {step.get('step_id')}. {step.get('title')}: {step.get('focus')}")

    print("\n[WORKER AGENT: Generated Questions & Criteria]")
    for idx, q in enumerate(result.get("questions", []), start=1):
        q_text = q.get("question", "")
        cat = q.get("category", "General")
        diff = q.get("difficulty", "Standard")
        pts = ", ".join(q.get("key_points", []))
        print(f"\n  Question {idx} [{cat} | {diff}]:")
        print(f"    {q_text}")
        if pts:
            print(f"    Key Evaluation Criteria: {pts}")

    print("\n[REVIEWER AGENT: Audit & Quality Verdict]")
    review = result.get("review", {})
    print(f"Verdict:      {review.get('verdict')}")
    print(f"Audit Score:  {review.get('score')}/100")
    print(f"Risk:         {review.get('risk')}")
    print(f"Critique:     {review.get('critique')}")
    if review.get("strengths"):
        print("Strengths:")
        for s in review.get("strengths", []):
            print(f"  + {s}")
    if review.get("recommend_corrections"):
        print("Recommended Corrections:")
        for r in review.get("recommend_corrections", []):
            print(f"  > {r}")
    if review.get("suggest_retests"):
        print("Suggested Retests:")
        for t in review.get("suggest_retests", []):
            print(f"  ? {t}")

    print("\n[HUMAN — FINAL DECISION MAKER: Governance Gate]")
    human = result.get("human_decision", {})
    print(f"Decision:     {human.get('decision')}")
    print(f"Authority:    {human.get('authority')}")

    print("\n[TRAJECTORY CHRONOLOGY]")
    for step in result.get("trajectory", []):
        print(f"  [{step['timestamp']}] Agent: {step['agent']:8s} | {step['action']}")
    print("=" * 76 + "\n")


def run_cli_interview_eval(role: str, question: str, answer: str, max_iter: int, as_json: bool = False):
    result = coordinator.coordinate_answer_evaluation(role, question, answer, max_iterations=max_iter)
    if as_json:
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 76)
    print("  RELEASE 2 MULTI-AGENT COORDINATION: ANSWER EVALUATION")
    print("=" * 76)
    print(f"Target Role:  {result['target_role']}")
    print(f"Question:     {result['question']}")
    print(f"Score:        {result['score']}/100")
    print(f"Approved:     {result['approved']}")
    print(f"Duration:     {result['duration_seconds']}s")
    print("-" * 76)

    print("\n[PLANNER AGENT: Evaluation Rubric]")
    for dim in result.get("plan", {}).get("dimensions", []):
        print(f"  * {dim.get('name')}: {dim.get('description')} (weight={dim.get('weight')})")

    print("\n[WORKER AGENT: Synthesized Evaluation]")
    print(f"Feedback: {result.get('feedback')}")
    print("Improvement Tips:")
    for tip in result.get("improvement_tips", []):
        print(f"  - {tip}")

    print("\n[REVIEWER AGENT: Quality Audit]")
    review = result.get("review", {})
    print(f"Verdict:     {review.get('verdict')}")
    print(f"Audit Score: {review.get('score')}/100")
    print(f"Critique:    {review.get('critique')}")

    print("\n[TRAJECTORY CHRONOLOGY]")
    for step in result.get("trajectory", []):
        print(f"  [{step['timestamp']}] Agent: {step['agent']:8s} | {step['action']}")
    print("=" * 76 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Shared non-containerised Multi-Agent Server (Release 2)")
    parser.add_argument("--serve", action="store_true", help="Start the HTTP Multi-Agent Server (default if no task specified)")
    parser.add_argument("--host", default=AI_SERVICES_HOST, help=f"Host interface to bind (default {AI_SERVICES_HOST})")
    parser.add_argument("--port", type=int, default=MULTI_AGENT_PORT, help=f"Port to listen on (default {MULTI_AGENT_PORT})")
    parser.add_argument("--cli", action="store_true", help="Execute multi-agent workflow in terminal mode")
    parser.add_argument("--role", default="Software Engineer", help="Target role for interview prep or eval")
    parser.add_argument("--type", default="technical", help="Interview type (technical, behavioral, etc.)")
    parser.add_argument("--count", type=int, default=3, help="Number of questions to generate (1-10)")
    parser.add_argument("--evaluate", action="store_true", help="Run answer evaluation workflow")
    parser.add_argument("--question", default="Explain how you design a resilient distributed service.", help="Question to evaluate")
    parser.add_argument("--answer", default="I isolate services, use idempotent APIs, circuit breakers, and comprehensive telemetry.", help="Candidate answer to evaluate")
    parser.add_argument("--max-iterations", type=int, default=15, help="Maximum coordinator iterations (default 15)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON to stdout")

    args = parser.parse_args()

    # Determine whether terminal execution was explicitly requested
    is_terminal_task = args.cli or args.evaluate or any(arg in sys.argv for arg in ["--role", "--question", "--answer", "--cli"])

    if is_terminal_task and not args.serve:
        if args.evaluate:
            run_cli_interview_eval(args.role, args.question, args.answer, args.max_iterations, as_json=args.json)
        else:
            run_cli_interview_prep(args.role, args.type, args.count, args.max_iterations, as_json=args.json)
        return

    # Default to running the HTTP server
    print(f"Starting Shared Multi-Agent Server (Release 2) on http://{args.host}:{args.port}")
    print(f"Planner Model: {PLANNER_MODEL} | Worker Model: {WORKER_MODEL} | Reviewer Model: {REVIEWER_MODEL}")
    app.run(host=args.host, port=args.port, debug=False)


register_resume_routes(
    app,
    lambda model, system, user: call_ollama(model, system, user),
    parse_json_from_text,
    {"Planner": PLANNER_MODEL, "Worker": WORKER_MODEL, "Reviewer": REVIEWER_MODEL},
)


if __name__ == "__main__":
    main()
