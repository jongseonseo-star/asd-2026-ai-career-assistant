from __future__ import annotations

import json
from typing import Any

FEEDBACK_HEADINGS = ("Strengths", "Skill Gaps", "Recommended Actions", "Information Missing")


class DependencyError(Exception):
    def __init__(
        self, dependency: str, message: str, status_code: int = 503
    ) -> None:
        super().__init__(message)
        self.dependency = dependency
        self.message = message
        self.status_code = status_code

def build_evidence_sources(
    profile: dict[str, Any], resume: dict[str, Any], skills: list[dict[str, Any]],
    job_description: str, guidance: list[dict[str, Any]],
) -> list[dict[str, str]]:
    # Source identifiers are assigned by the application from retrieved records;
    # the language model cannot supply its own source catalogue.
    profile_evidence = (
        f"Target role (goal): {profile.get('target_role', '')}\n"
        f"Career summary: {profile.get('career_summary') or 'Not supplied'}"
    )
    sources = [
        {"id": "C1", "kind": "candidate", "title": "Candidate profile", "source": f"db://student-2/profiles/{profile['id']}", "text": profile_evidence},
        {"id": "R1", "kind": "candidate", "title": "Selected resume", "source": f"db://student-2/resumes/{resume['id']}", "text": resume["content"]},
    ]
    for index, skill in enumerate(skills, 1):
        years = skill.get("years_experience")
        experience = f"{years} years" if isinstance(years, (int, float)) and not isinstance(years, bool) else "Not supplied"
        evidence = (
            f"Recorded skill: {skill['skill_name']}.\n"
            f"Proficiency: {skill.get('proficiency_level') or 'Not supplied'}.\n"
            f"Recorded experience: {experience}."
        )
        sources.append({"id": f"S{index}", "kind": "candidate", "title": "Candidate skill", "source": f"db://student-2/skills/{skill['id']}", "text": evidence})
    if job_description:
        sources.append({"id": "J1", "kind": "requirement", "title": "Supplied job requirements", "source": "request://job-description", "text": job_description})
    for index, item in enumerate(guidance, 1):
        sources.append({"id": f"G{index}", "kind": "guidance", "title": item["title"], "source": item["source"], "text": item["text"]})
    return sources

def validate_cited_feedback(raw: str, sources: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """Check citation integrity; this is not a claim of semantic correctness."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise DependencyError("ollama-output", "AI returned invalid structured feedback. Try again.", 502) from error
    source_map = {source["id"]: source for source in sources}
    if not isinstance(payload, dict) or set(payload) != set(FEEDBACK_HEADINGS):
        raise DependencyError("ollama-output", "AI returned an incomplete feedback structure. Try again.", 502)
    for heading in FEEDBACK_HEADINGS:
        items = payload[heading]
        if not isinstance(items, list) or not 1 <= len(items) <= 3:
            raise DependencyError("ollama-output", "AI returned invalid feedback items. Try again.", 502)
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != {"text", "citations"}
                or not isinstance(item["text"], str)
                or not item["text"].strip()
                or len(item["text"]) > 500
                or len(item["text"].split()) > 40
                or not isinstance(item["citations"], list)
                or len(item["citations"]) > 8
                or any(not isinstance(ref, str) or ref not in source_map for ref in item["citations"])
                or (heading != "Information Missing" and not item["citations"])
            ):
                raise DependencyError("ollama-output", "AI returned unsupported or missing citations. Try again.", 502)
            if heading == "Strengths" and any(source_map[ref]["kind"] != "candidate" for ref in item["citations"]):
                raise DependencyError("ollama-output", "AI used requirements or guidance as candidate evidence. Try again.", 502)
            if heading == "Skill Gaps":
                kinds = {source_map[ref]["kind"] for ref in item["citations"]}
                if "candidate" not in kinds or (any(source["kind"] == "requirement" for source in sources) and "requirement" not in kinds):
                    raise DependencyError("ollama-output", "AI skill comparisons must cite candidate evidence and the supplied requirements. Try again.", 502)
            # Disallow additional model-written reference tokens in prose.
            if "[" in item["text"] or "]" in item["text"]:
                raise DependencyError("ollama-output", "AI returned references outside its citation fields. Try again.", 502)
    if sum(len(item["text"].split()) for items in payload.values() for item in items) > 220:
        raise DependencyError("ollama-output", "AI feedback exceeded the concise output limit. Try again.", 502)
    return payload

def feedback_schema(sources: list[dict[str, str]]) -> dict[str, Any]:
    properties = {}
    for heading in FEEDBACK_HEADINGS:
        allowed = [source["id"] for source in sources if heading != "Strengths" or source["kind"] == "candidate"]
        properties[heading] = {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {
                "type": "object", "required": ["text", "citations"], "additionalProperties": False,
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 500},
                    "citations": {"type": "array", "minItems": 0 if heading == "Information Missing" else 1, "maxItems": 8,
                                  "items": {"type": "string", "enum": allowed}},
                },
            },
        }
        if heading == "Skill Gaps":
            candidate_ids = [source["id"] for source in sources if source["kind"] == "candidate"]
            requirement_ids = [source["id"] for source in sources if source["kind"] == "requirement"]
            citations = properties[heading]["items"]["properties"]["citations"]
            if requirement_ids:
                # Structured generation must name both sides of a comparison.
                citations.update({"items": [{"type": "string", "enum": candidate_ids},
                                            {"type": "string", "enum": requirement_ids}],
                                  "minItems": 2, "maxItems": 2})
            else:
                citations["items"]["enum"] = candidate_ids
    return {"type": "object", "properties": properties, "required": list(FEEDBACK_HEADINGS), "additionalProperties": False}
