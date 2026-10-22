"""Validation shared by the job API and its local RAG adapter."""
from __future__ import annotations

import json
from uuid import UUID

HUMAN_DECISIONS = ["Accept", "Partially Accept", "Reject"]


def nonempty_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000


def text_list(value, minimum: int = 0) -> bool:
    return isinstance(value, list) and minimum <= len(value) <= 10 and all(nonempty_text(item) for item in value)


def agent_schema(stage: str, context: dict) -> dict:
    text = {"type": "string", "minLength": 1, "maxLength": 600}
    items = {"type": "array", "items": text, "minItems": 1, "maxItems": 3}
    if stage == "plan":
        properties = {key: items for key in ("steps", "evidence_requirements", "approval_checkpoints")}
    elif stage == "work":
        claim = {"type": "object", "additionalProperties": False, "required": ["text", "sources"],
                 "properties": {"text": text, "sources": {"type": "array", "minItems": 1, "maxItems": 3,
                    "items": {"type": "string", "enum": context["sources"]}}}}
        properties = {"claims": {"type": "array", "minItems": 1, "maxItems": 3, "items": claim}}
    else:
        properties = {"verdict": {"type": "string", "enum": ["approved", "needs_revision"]}, "risk": text,
                      "recommend_corrections": {**items, "minItems": 0}, "suggest_retests": {**items, "minItems": 0}}
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def validate_agent_stage(stage: str, output: dict, context: dict) -> None:
    if not isinstance(output, dict):
        raise ValueError("Agent output must be an object.")
    if stage == "plan":
        if any(not text_list(output.get(key), 1) for key in ("steps", "evidence_requirements", "approval_checkpoints")):
            raise ValueError("The plan requires steps, evidence requirements and approval checkpoints.")
    elif stage == "work":
        claims = output.get("claims")
        if not isinstance(claims, list) or not 1 <= len(claims) <= 6:
            raise ValueError("The worker must provide between one and six cited claims.")
        for claim in claims:
            if (not isinstance(claim, dict) or not nonempty_text(claim.get("text"))
                    or not text_list(claim.get("sources"), 1)
                    or any(source not in context["sources"] for source in claim["sources"])):
                raise ValueError("Worker claims must cite the selected job's database evidence.")
    elif stage == "review":
        if (output.get("verdict") not in ("approved", "needs_revision") or not nonempty_text(output.get("risk"))
                or any(not text_list(output.get(key)) for key in ("recommend_corrections", "suggest_retests"))):
            raise ValueError("The review requires a verdict, risks, corrections and retests.")


def validate_human_decision(data: dict) -> None:
    if (not isinstance(data, dict) or set(data) != {"decision", "reason", "evidence_used"}
            or data.get("decision") not in HUMAN_DECISIONS
            or not nonempty_text(data.get("reason")) or not nonempty_text(data.get("evidence_used"))):
        raise ValueError("Select a decision and provide a reason and the evidence used (up to 2000 characters each).")


def validate_job_analysis(payload: dict, job_id: int, context: dict | None = None) -> None:
    if not isinstance(payload, dict) or not positive_id(payload.get("job_id")) or payload["job_id"] != job_id:
        raise ValueError("The analysis does not match the selected job.")
    UUID(payload.get("run_id", ""))
    supplied = payload.get("job_context")
    validate_context(supplied, job_id)
    if context is not None and supplied != context:
        raise ValueError("The analysis changed the supplied database evidence.")
    for stage in ("plan", "work", "review"):
        validate_agent_stage(stage, payload.get(stage), supplied)
    human = payload.get("human_decision")
    if (not isinstance(human, dict) or human.get("required") is not True
            or human.get("available_decisions") != HUMAN_DECISIONS):
        raise ValueError("The result must require human review.")
    if payload.get("status") == "awaiting-human-review":
        if human.get("status") != "pending" or any(human.get(key) is not None for key in ("decision", "reason", "evidence_used")):
            raise ValueError("Agent output must not contain an automatic human decision.")
    elif payload.get("status") == "completed" and human.get("status") == "recorded":
        validate_human_decision({key: human.get(key) for key in ("decision", "reason", "evidence_used")})
    else:
        raise ValueError("Invalid job review status.")
    trajectory = payload.get("trajectory")
    if (not isinstance(trajectory, list) or not trajectory or len(trajectory) > 7
            or any(not isinstance(entry, dict) or not isinstance(entry.get("output"), dict)
                   or any(not nonempty_text(entry.get(key)) for key in ("agent", "stage", "timestamp"))
                   for entry in trajectory)):
        raise ValueError("The analysis is missing its agent trajectory.")
    if not nonempty_text(payload.get("query")) or type(payload.get("iterations")) is not int or payload["iterations"] not in (1, 2):
        raise ValueError("Invalid analysis question or iteration count.")


def positive_id(value) -> bool:
    return type(value) is int and value > 0


def validate_context(context: dict, job_id: int | None = None) -> None:
    if not isinstance(context, dict):
        raise ValueError("Job context must be an object.")
    job, company, skills = (context.get(key) for key in ("job", "company", "skills"))
    if not isinstance(job, dict) or not positive_id(job.get("id")):
        raise ValueError("Job context requires a valid job record.")
    if job_id is not None and job["id"] != job_id:
        raise ValueError("Job context does not match the selected posting.")
    if not isinstance(company, dict) or not positive_id(company.get("id")) or job.get("company_id") != company["id"]:
        raise ValueError("Company does not match the selected posting.")
    for record, fields in ((job, ("title", "description")), (company, ("name",))):
        if any(not isinstance(record.get(field), str) or not record[field].strip() for field in fields):
            raise ValueError("Job context is missing required text.")
    if not isinstance(skills, list) or len(skills) > 100:
        raise ValueError("Job context requires at most 100 skill records.")
    if any(not isinstance(skill, dict) or not positive_id(skill.get("id"))
           or skill.get("job_posting_id") != job["id"]
           or not isinstance(skill.get("skill_name"), str) or not skill["skill_name"].strip()
           for skill in skills):
        raise ValueError("Skill records must belong to the selected posting.")
    expected = {f"db://student-4/job_postings/{job['id']}", f"db://student-4/companies/{company['id']}"}
    expected.update(f"db://student-4/job_skills/{skill['id']}" for skill in skills)
    sources = context.get("sources")
    if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources) or set(sources) != expected:
        raise ValueError("Job context is missing its database source references.")
    if len(json.dumps(context)) > 24000:
        raise ValueError("Job context exceeds the supported size.")


def evidence_sources(context: dict, guidance: list[dict]) -> list[dict]:
    validate_context(context)
    records = [("job_postings", context["job"]), ("companies", context["company"])]
    records.extend(("job_skills", skill) for skill in context["skills"])
    sources = [{"id": f"J{number}", "kind": "job-record", "title": resource,
                "source": f"db://student-4/{resource}/{record['id']}",
                "text": json.dumps(record, ensure_ascii=False, sort_keys=True)}
               for number, (resource, record) in enumerate(records, 1)]
    sources.extend({"id": f"G{number}", "kind": "guidance", "title": item["title"],
                    "source": item["source"], "text": item["text"]}
                   for number, item in enumerate(guidance, 1))
    return sources


def answer_schema(sources: list[dict]) -> dict:
    record_ids = [source["id"] for source in sources if source["kind"] == "job-record"]
    guidance_ids = [source["id"] for source in sources if source["kind"] == "guidance"]
    citations = {
        "type": "array",
        "prefixItems": [
            {"type": "string", "enum": record_ids},
            {"type": "string", "enum": guidance_ids},
        ],
        "minItems": 2,
        "maxItems": 2,
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "citations"],
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 1200},
            "citations": citations,
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims"],
        "properties": {"claims": {"type": "array", "minItems": 1, "maxItems": 3, "items": claim}},
    }


def validate_claims(value, sources: list[dict]) -> list[dict]:
    if not isinstance(value, dict) or set(value) != {"claims"}:
        raise ValueError("The model must return a claims object.")
    claims = value["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= 3:
        raise ValueError("The answer must contain between one and three claims.")
    known = {source["id"]: source["kind"] for source in sources}
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"text", "citations"}:
            raise ValueError("Each answer claim requires text and citations.")
        text, citations = claim["text"], claim["citations"]
        if not isinstance(text, str) or not text.strip() or len(text) > 1200:
            raise ValueError("Answer text is empty or too long.")
        if (not isinstance(citations, list) or len(citations) != 2
                or any(not isinstance(citation, str) or citation not in known for citation in citations)):
            raise ValueError("Answer citations must identify supplied evidence.")
        if [known[citation] for citation in citations] != ["job-record", "guidance"]:
            raise ValueError("Each claim must cite a job record followed by retrieved guidance.")
    return claims


def validate_answer(payload: dict, context: dict) -> None:
    if not isinstance(payload, dict) or payload.get("confidence") not in {"low", "medium", "high"}:
        raise ValueError("RAG returned an invalid confidence category.")
    if not isinstance(payload.get("confidence_basis"), str) or not payload["confidence_basis"].strip():
        raise ValueError("RAG did not explain its confidence category.")
    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict) or retrieval.get("feature") != "jobs" or not isinstance(retrieval.get("results"), list):
        raise ValueError("RAG did not return job retrieval evidence.")
    if payload["confidence"] != retrieval.get("confidence"):
        raise ValueError("Answer confidence does not match retrieval.")
    guidance = retrieval["results"]
    for item in guidance:
        if (not isinstance(item, dict) or item.get("feature") != "jobs"
                or any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("title", "text", "source"))
                or not item["source"].startswith("repo://ai-services/knowledge/jobs/")):
            raise ValueError("RAG returned an invalid job guidance source.")
    if payload.get("evidence_sources") != evidence_sources(context, guidance):
        raise ValueError("RAG evidence does not match the selected job and retrieved guidance.")
    if payload.get("sources") != [item["source"] for item in guidance]:
        raise ValueError("RAG citations do not match retrieval.")
    metadata = payload.get("generation_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("RAG generation metadata is missing.")
    if not guidance:
        if (payload.get("status") != "insufficient-context" or payload["confidence"] != "low"
                or payload.get("claims") != [] or metadata.get("called") is not False):
            raise ValueError("An unmatched query must not produce generated claims.")
    else:
        if payload.get("status") != "answered" or metadata.get("called") is not True:
            raise ValueError("RAG did not generate an answer from the retrieved context.")
        validate_claims({"claims": payload.get("claims")}, payload["evidence_sources"])
    if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        raise ValueError("RAG did not return displayable answer text.")
