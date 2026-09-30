"""Validation shared by the job API and its local RAG adapter."""
from __future__ import annotations

import json


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
