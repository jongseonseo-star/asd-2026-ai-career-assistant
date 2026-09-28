"""Record local validation evidence; a successful HTTP response alone never passes."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
from loop_evidence import assessment_evidence
from loop_collectors import collect_db, collect_endpoints, collect_architecture, collect_devops

LEGACY_MODES = ("db", "endpoints", "architecture", "devops")
SINGLE_MODES = (*LEGACY_MODES, "mcp", "rag")
MODES = {*SINGLE_MODES, "release0", "all"}
SECTIONS = ("Strengths", "Skill Gaps", "Recommended Actions", "Information Missing")
NO_CONTEXT_QUERY = "What is the weather in Sydney?"
PROMPT_DIR = SERVICE_DIR / "prompts" / "loop"


def assessment_prompt(role, mode):
    family = "legacy_" if mode in LEGACY_MODES else ""
    paths = [PROMPT_DIR / f"{family}{role}.txt", PROMPT_DIR / f"{mode}.txt"]
    if mode == "rag" and role == "review":
        paths.append(PROMPT_DIR / "rag_reasoning.txt")
    content = [path.read_text(encoding="utf-8").strip() for path in paths]
    if not all(content):
        raise ValueError("An assessment prompt is empty.")
    return "\n\n".join(content), [str(path) for path in paths]


def call_assessment(role: str, model: str, observed: dict, *, base_url: str, timeout: float,
                    implementation: str | None = None) -> dict:
    started = time.monotonic()
    user_input = {"observed_evidence": observed}
    if implementation is not None:
        user_input["implementation_assessment"] = implementation
    requested_word_limit = 60 if observed["mode"] in LEGACY_MODES else 80
    prompt, prompt_paths = assessment_prompt(role, observed["mode"])
    body = {"model": model, "stream": False,
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)}],
        "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192}}
    result = {"role": role, "model": model, "started_at": timestamp(), "url": base_url + "/api/chat",
              "request": body, "prompt_paths": prompt_paths, "completed": False}
    request = Request(result["url"], data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            result["status"] = response.status
            payload = json.loads(response.read())
        output = payload.get("message", {}).get("content") if isinstance(payload, dict) else None
        # Preserve failed/truncated responses too: a token-limit failure must be diagnosable.
        if isinstance(payload, dict):
            result["generation_metadata"] = {key: payload[key] for key in (
                "model", "done", "done_reason", "prompt_eval_count", "eval_count", "total_duration") if key in payload}
        if isinstance(output, str):
            result.update(raw_output=output[:8000], raw_output_truncated=len(output) > 8000)
        if (result["status"] != 200 or not isinstance(output, str) or not output.strip()
                or len(output) > 4000 or payload.get("done") is False or payload.get("done_reason") == "length"):
            raise ValueError("The model did not return a complete, non-empty assessment.")
        result.update({"completed": True, "output": output.strip(), "word_count": len(output.split()),
            "requested_word_limit": requested_word_limit,
            "within_requested_word_limit": len(output.split()) <= requested_word_limit,
            "generation_metadata": {key: payload[key] for key in (
                "model", "done", "done_reason", "prompt_eval_count", "eval_count", "total_duration") if key in payload}})
    except (HTTPError, URLError, OSError, ValueError, TypeError, AttributeError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result.update({"finished_at": timestamp(), "duration_seconds": round(time.monotonic() - started, 3)})
    return result


def assess_checks(mode: str, feature: str, checks: list[dict], *, base_url: str, timeout: float) -> dict:
    observed = assessment_evidence(mode, feature, checks)
    # Do not silently remove facts or citation mappings to squeeze a large case into context.
    if len(json.dumps(observed, ensure_ascii=False)) > 24000:
        return {"status": "failed", "error": "Complete assessment evidence exceeds the 24,000-character budget. Select a smaller case; candidate facts and citation mappings were not truncated.",
                "observed_evidence": observed}
    try:
        implementation = call_assessment("implementation", os.getenv("IMPLEMENTATION_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")),
            observed, base_url=base_url, timeout=timeout)
        if mode in {"db", "endpoints"}:
            return {"status": "completed" if implementation["completed"] else "failed", "implementation": implementation,
                    "review": {"required": False, "reason": "Lab 4 DB/endpoints use one assessment model."}}
        if implementation["completed"]:
            review = call_assessment("review", os.getenv("REVIEW_MODEL", os.getenv("OLLAMA_REVIEW_MODEL", "llama3.1:8b")), observed,
                base_url=base_url, timeout=timeout, implementation=implementation["output"])
        else:
            review = {"role": "review", "model": os.getenv("REVIEW_MODEL", "llama3.1:8b"),
                      "completed": False, "skipped": "Implementation assessment failed; no output to review."}
        return {"status": "completed" if implementation["completed"] and review["completed"] else "failed",
                "implementation": implementation, "review": review}
    except (OSError, ValueError) as error:
        return {"status": "failed", "error": f"Assessment evidence or prompt unavailable: {error}"}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def positive_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def finish_check(result: dict, errors: list[str], started: float) -> dict:
    result.update({"finished_at": timestamp(), "duration_seconds": round(time.monotonic() - started, 3),
                   "passed": not errors, "validation_errors": errors})
    return result


def check(url: str, payload: dict | None = None, *, name: str = "http", validator=None,
          timeout: float = 180, expected_status: int = 200) -> dict:
    started = time.monotonic()
    result = {"name": name, "started_at": timestamp(), "url": url,
              "request": {"method": "POST" if payload is not None else "GET", "body": payload}}
    request = Request(url, method=result["request"]["method"])
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.data = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(request, timeout=timeout) as response:
            result.update({"status": response.status, "payload": json.loads(response.read())})
        errors = [] if result["status"] == expected_status else [f"Expected HTTP {expected_status}, received {result['status']}."]
        if not errors:
            errors.extend(validator(result["payload"]) if validator else ["No payload validator configured."])
    except HTTPError as error:
        result.update({"status": error.code, "error": str(error)})
        try:
            result["payload"] = json.loads(error.read())
        except (ValueError, OSError):
            pass
        errors = (validator(result.get("payload")) if validator else ["No payload validator configured."]) if error.code == expected_status else [f"HTTP request failed with status {error.code}."]
    except (OSError, URLError, ValueError) as error:
        result.update({"status": 503, "error": str(error)})
        errors = ["Request timed out, failed, or returned invalid JSON."]
    return finish_check(result, errors, started)


def validate_mcp_payload(payload, feature: str, profile_id: int, resume_id: int, target_role: str) -> list[str]:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("status_code", 200) != 200:
        return ["MCP did not return a successful structured tool result."]
    if feature == "interview":
        errors = []
        if payload.get("target_role") != target_role or not nonempty(payload.get("question_guidance")):
            errors.append("Interview role or question guidance is missing or inconsistent.")
        dimensions = payload.get("evaluation_dimensions")
        if not isinstance(dimensions, list) or not dimensions or not all(nonempty(item) for item in dimensions):
            errors.append("Interview evaluation dimensions are missing or invalid.")
        return errors
    profile, resume, skills = (payload.get(key) for key in ("candidate_profile", "resume", "candidate_skills"))
    errors = []
    if not isinstance(profile, dict) or not positive_id(profile.get("id")) or profile.get("id") != profile_id:
        errors.append("Candidate profile does not match the requested profile ID.")
    if not isinstance(resume, dict) or not positive_id(resume.get("id")) or not positive_id(resume.get("candidate_profile_id")) or resume.get("id") != resume_id or resume.get("candidate_profile_id") != profile_id or not nonempty(resume.get("content")):
        errors.append("Resume is missing, empty, or not owned by the requested profile.")
    if not isinstance(skills, list) or any(not isinstance(skill, dict) or not positive_id(skill.get("id")) or not positive_id(skill.get("candidate_profile_id")) or skill.get("candidate_profile_id") != profile_id or not nonempty(skill.get("skill_name")) for skill in skills):
        errors.append("Candidate skills do not belong to the requested profile.")
    sources = payload.get("sources")
    expected = {f"db://student-2/profiles/{profile_id}", f"db://student-2/resumes/{resume_id}"}
    if isinstance(skills, list):
        expected.update(f"db://student-2/skills/{skill['id']}" for skill in skills if isinstance(skill, dict) and positive_id(skill.get("id")))
    if not isinstance(sources, list) or not all(nonempty(source) for source in sources) or not expected.issubset(sources):
        errors.append("MCP result is missing the requested database source references.")
    return errors


async def check_mcp(*, base_url: str | None = None, feature: str = "resume", profile_id: int = 1,
                    resume_id: int = 1, target_role: str = "Software Engineer", timeout: float = 180,
                    required_tools: tuple[str, ...] = ()) -> dict:
    started = time.monotonic()
    tool_name = f"{feature}_context"
    arguments = {"profile_id": profile_id, "resume_id": resume_id} if feature == "resume" else {"target_role": target_role}
    result = {"name": "mcp-tool-validation", "protocol": "MCP", "started_at": timestamp(),
              "url": (base_url or os.getenv("MCP_BASE_URL", "http://127.0.0.1:8765")).rstrip("/") + "/mcp",
              "request": {"tool": tool_name, "arguments": arguments}}

    async def interaction():
        from fastmcp import Client

        async with Client(result["url"], timeout=timeout) as client:
            registered = await client.list_tools()
            result["registered_tools"] = [{"name": tool.name, "input_schema": tool.inputSchema} for tool in registered]
            missing = set(required_tools) - {tool.name for tool in registered}
            if missing:
                return ["Required RAG MCP tools are not registered: " + ", ".join(sorted(missing))]
            selected = next((tool for tool in registered if tool.name == tool_name), None)
            if selected is None:
                return [f"Required MCP tool {tool_name} is not registered."]
            if not isinstance(selected.inputSchema, dict) or not set(arguments).issubset(selected.inputSchema.get("properties", {})):
                return ["Registered MCP tool input schema does not expose the requested arguments."]
            response = await client.call_tool(tool_name, arguments=arguments, timeout=timeout)
            result["payload"] = response.structured_content
            result["is_error"] = bool(response.is_error)
            if result["is_error"]:
                return ["MCP returned a tool execution error."]
            return validate_mcp_payload(result["payload"], feature, profile_id, resume_id, target_role)

    try:
        errors = await asyncio.wait_for(interaction(), timeout=timeout)
        result["status"] = 200
    except Exception as error:
        # SDK transport failures may be nested ExceptionGroups. Preserve evidence
        # and fail rather than losing the entire validation capture.
        result.update({"status": 503, "error": f"{type(error).__name__}: {error}"})
        errors = ["MCP interaction failed or exceeded the configured time limit."]
    return finish_check(result, errors, started)


def validate_corpus(payload, feature: str) -> list[str]:
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("corpora"), dict):
        return ["RAG corpus status is missing."]
    corpus = payload["corpora"].get(feature)
    if not isinstance(corpus, dict):
        return [f"No active corpus for {feature}; refresh the approved corpus before validation."]
    errors = []
    if corpus.get("feature") != feature or corpus.get("stale") is not False:
        errors.append("Active corpus is stale or belongs to the wrong feature.")
    if corpus.get("embedding_dimensions") != 256 or not nonempty(corpus.get("embedding_version")):
        errors.append("Active corpus must identify the local 256-dimension embedding.")
    if not positive_id(corpus.get("chunk_count")) or not positive_id(corpus.get("document_count")):
        errors.append("Active corpus has no indexed documents/chunks.")
    if any(not nonempty(corpus.get(key)) for key in ("collection", "corpus_version", "indexed_at", "corpus_sha256")):
        errors.append("Active corpus is missing index/version/provenance metadata.")
    return errors


def validate_retrieval(payload, feature: str, *, empty: bool = False, corpus_version: str | None = None) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return ["RAG retrieval must contain a results list."]
    errors = []
    results = payload["results"]
    if payload.get("feature") != feature:
        errors.append("RAG retrieval feature does not match the request.")
    if payload.get("retrieval_mode") != "vector" or payload.get("vector_store_status") != "ready":
        errors.append("Full course validation requires working vector retrieval; lexical fallback is degraded.")
    if payload.get("embedding_dimensions") != 256 or not nonempty(payload.get("embedding_version")):
        errors.append("RAG retrieval does not identify the local 256-dimension embedding.")
    if not nonempty(payload.get("corpus_version")) or (corpus_version and payload.get("corpus_version") != corpus_version):
        errors.append("Retrieval is not tied to the observed active corpus version.")
    if payload.get("confidence") not in ("high", "medium", "low") or not nonempty(payload.get("confidence_basis")):
        errors.append("RAG confidence category or explanation is missing or invalid.")
    if empty:
        if results or payload.get("confidence") != "low":
            errors.append("An unmatched query must return no results and low confidence.")
    elif not results:
        errors.append("The positive retrieval query returned no context.")
    for item in results:
        if not isinstance(item, dict) or any(not nonempty(item.get(key)) for key in ("id", "title", "text", "source", "chunk_id", "source_id", "corpus_version")):
            errors.append("A retrieved document is missing its text or source identity.")
        elif item.get("feature") != feature or isinstance(item.get("score"), bool) or not isinstance(item.get("score"), (int, float)) or not math.isfinite(item["score"]) or item["score"] <= 0:
            errors.append("A retrieved document has the wrong feature or no positive relevance score.")
        elif item["corpus_version"] != payload.get("corpus_version") or item.get("authority_tier") not in ("tier_1", "tier_2", "tier_3"):
            errors.append("A retrieved chunk has inconsistent version or authority metadata.")
    return errors


def validate_answer(payload, *, empty: bool = False, corpus_version: str | None = None) -> list[str]:
    if not isinstance(payload, dict):
        return ["RAG answer must be a JSON object."]
    errors = validate_retrieval(payload.get("retrieval"), "resume", empty=empty, corpus_version=corpus_version)
    if payload.get("confidence") not in ("high", "medium", "low") or not nonempty(payload.get("confidence_basis")):
        errors.append("Answer confidence category or explanation is missing or invalid.")
    if not nonempty(payload.get("feedback")):
        errors.append("The answer does not contain displayable feedback.")
    metadata = payload.get("generation_metadata")
    if empty:
        if payload.get("status") != "insufficient-context" or payload.get("confidence") != "low":
            errors.append("No-context answer must explicitly report insufficient context with low confidence.")
        if payload.get("sources") != [] or payload.get("feedback_sections") != {}:
            errors.append("No-context answer must not include generated claims or guidance citations.")
        if not isinstance(metadata, dict) or metadata.get("called") is not False:
            errors.append("No-context answer must record that generation was not called.")
        return errors
    if payload.get("status") != "answered" or not nonempty(payload.get("model")):
        errors.append("The positive query did not return a model-generated answer.")
    if not isinstance(metadata, dict) or metadata.get("called") is not True:
        errors.append("The answer does not record an actual model generation call.")
    retrieved = payload.get("retrieval", {})
    if isinstance(retrieved, dict) and payload.get("confidence") != retrieved.get("confidence"):
        errors.append("Answer confidence must match its recorded retrieval confidence.")
    retrieval_sources = {item["source"] for item in retrieved.get("results", []) if isinstance(item, dict) and nonempty(item.get("source"))} if isinstance(retrieved, dict) and isinstance(retrieved.get("results"), list) else set()
    retrieval_text = {item["source"]: item.get("text") for item in retrieved.get("results", []) if isinstance(item, dict) and nonempty(item.get("source"))} if isinstance(retrieved, dict) and isinstance(retrieved.get("results"), list) else {}
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources or not all(nonempty(source) and source in retrieval_sources for source in sources):
        errors.append("Answer guidance citations must refer to retrieved sources.")
    evidence = payload.get("evidence_sources")
    evidence_by_id = {}
    if not isinstance(evidence, list) or not evidence:
        errors.append("Answer evidence sources are missing.")
    else:
        for source in evidence:
            if not isinstance(source, dict) or any(not nonempty(source.get(key)) for key in ("id", "kind", "source", "text")):
                errors.append("An answer evidence source has no identity, provenance, or text.")
            elif source["id"] in evidence_by_id:
                errors.append("Answer evidence source IDs must be unique.")
            else:
                evidence_by_id[source["id"]] = source
                if source["kind"] == "guidance" and source["source"] not in retrieval_sources:
                    errors.append("A guidance evidence source was not present in retrieval.")
                elif source["kind"] == "guidance" and source["text"] != retrieval_text[source["source"]]:
                    errors.append("A guidance evidence source does not preserve its retrieved text.")
    sections = payload.get("feedback_sections")
    if not isinstance(sections, dict) or set(sections) != set(SECTIONS):
        return errors + ["The answer must contain all four expected feedback sections."]
    for section in SECTIONS:
        items = sections[section]
        if not isinstance(items, list) or not items:
            errors.append(f"The {section} section is empty or invalid.")
            continue
        for item in items:
            if not isinstance(item, dict) or not nonempty(item.get("text")) or not isinstance(item.get("citations"), list):
                errors.append(f"The {section} section contains malformed feedback.")
                continue
            citations = item["citations"]
            if (not citations and section != "Information Missing") or any(not isinstance(ref, str) or ref not in evidence_by_id for ref in citations):
                errors.append(f"The {section} section contains missing or unknown citations.")
            elif section == "Strengths" and any(evidence_by_id[ref]["kind"] != "candidate" for ref in citations):
                errors.append("Strengths must cite candidate evidence.")
            elif section == "Skill Gaps" and any(source["kind"] == "requirement" for source in evidence_by_id.values()):
                cited_kinds = {evidence_by_id[ref]["kind"] for ref in citations}
                if not {"candidate", "requirement"}.issubset(cited_kinds):
                    errors.append("Skill gaps must cite both the candidate evidence and supplied job requirements.")
    return errors


def capture_mode(mode: str, *, feature: str = "resume", profile_id: int = 1,
        resume_id: int = 1, target_role: str = "Software Engineer", query: str | None = None,
        job_description: str = "Python API development, Docker, tests, and evidence of project outcomes.",
        timeout: float = 180, checks_only: bool = False, project_root: str | None = None,
        compose_files: list[str] | None = None, compose_project: str | None = None,
        ci_evidence_dir: str | None = None) -> dict:
    if mode not in SINGLE_MODES or feature not in {"resume", "interview"} or not 0 < timeout <= 600:
        raise ValueError("Unsupported mode/feature or timeout outside (0, 600] seconds.")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (profile_id, resume_id)):
        raise ValueError("Profile and resume IDs must be positive integers.")
    started_at = timestamp()
    bases = {"mcp": os.getenv("MCP_BASE_URL", "http://127.0.0.1:8765").rstrip("/"),
             "rag": os.getenv("RAG_BASE_URL", "http://127.0.0.1:8766").rstrip("/"),
             "ollama": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/").removesuffix("/v1"),
             "database": os.getenv("STUDENT2_DATABASE_URL", "http://127.0.0.1:5002").rstrip("/"),
             "backend": os.getenv("STUDENT2_BACKEND_URL", "http://127.0.0.1:5001").rstrip("/"),
             "frontend": os.getenv("STUDENT2_FRONTEND_URL", "http://127.0.0.1:8082").rstrip("/")}
    root = Path(project_root).resolve() if project_root else SERVICE_DIR.parent
    compose_paths = [Path(path).resolve() for path in compose_files] if compose_files else [root / "docker-compose.yml"]
    compose_project = compose_project or os.getenv("COMPOSE_PROJECT_NAME", "asd-2026-ai-career-assistant")
    reports = Path(ci_evidence_dir).resolve() if ci_evidence_dir else root / "reports/student-2"
    checks = []
    if mode in LEGACY_MODES and feature != "resume":
        checks = [{"name": "legacy-feature-scope", "passed": False,
                   "validation_errors": ["Release 0 collectors currently validate Student 2 only."]}]
    elif mode == "db":
        checks = collect_db(check, bases, timeout)
    elif mode == "endpoints":
        checks = collect_endpoints(check, bases, timeout)
    elif mode == "architecture":
        checks = collect_architecture(root, compose_paths, compose_project, timeout)
    elif mode == "devops":
        checks = collect_devops(root, reports)
    mcp_result = None
    if mode == "mcp" or (mode == "rag" and feature == "resume"):
        mcp_result = asyncio.run(check_mcp(base_url=bases["mcp"], feature=feature, profile_id=profile_id,
                                         resume_id=resume_id, target_role=target_role, timeout=timeout,
                                         required_tools=("refresh_corpus", "retrieve_context", "answer_question") if mode == "rag" else ()))
        checks.append(mcp_result)
    if mode == "rag":
        if feature != "resume":
            checks.append({"name": "rag-generated-answer", "passed": False, "validation_errors": [
                "The shared /answer service currently implements resume feedback only. Interview RAG generation is not validated by this loop."]})
        elif not mcp_result["passed"]:
            checks.append({"name": "rag-generated-answer", "passed": False, "validation_errors": [
                "RAG generation was not attempted because valid candidate context could not be obtained through MCP."]})
        else:
            corpus = check(bases["rag"] + "/corpus", name="rag-active-corpus",
                           validator=lambda body: validate_corpus(body, feature), timeout=timeout)
            checks.append(corpus)
            corpus_version = corpus["payload"]["corpora"][feature]["corpus_version"] if corpus["passed"] else None
            query = query or "resume skills evidence outcomes"
            request = {"query": query, "feature": feature, "top_k": 3}
            checks.append(check(bases["rag"] + "/retrieve", request, name="rag-retrieval",
                                validator=lambda body: validate_retrieval(body, feature, corpus_version=corpus_version), timeout=timeout))
            request = {**request, "task": "resume-feedback", "candidate_context": mcp_result["payload"], "job_description": job_description}
            checks.append(check(bases["rag"] + "/answer", request, name="rag-generated-answer",
                                validator=lambda body: validate_answer(body, corpus_version=corpus_version), timeout=timeout))
            checks.append(check(bases["rag"] + "/answer", {**request, "query": NO_CONTEXT_QUERY},
                                name="rag-insufficient-context", validator=lambda body: validate_answer(body, empty=True, corpus_version=corpus_version), timeout=timeout))
    checks_passed = bool(checks) and all(item["passed"] for item in checks)
    if checks_only:
        assessments = {"status": "skipped", "reason": "Explicit checks-only run; not a full agentic review."}
    else:
        assessments = assess_checks(mode, feature, checks, base_url=bases["ollama"], timeout=timeout)
    automation_passed = checks_passed and (checks_only or assessments["status"] == "completed")
    evidence = {"mode": mode, "feature": feature, "started_at": started_at, "finished_at": timestamp(),
                "configuration": {"base_urls": bases, "timeout_seconds": timeout, "profile_id": profile_id, "resume_id": resume_id,
                                  "project_root": str(root), "compose_project": compose_project,
                                  "compose_files": [str(path) for path in compose_paths], "ci_evidence_dir": str(reports)},
                "workflow": ["OBSERVE", "IMPLEMENTATION ASSESSMENT"] + ([] if mode in {"db", "endpoints"} else ["REVIEW ASSESSMENT"]) + ["HUMAN DECISION", "IMPROVE AND RETEST"],
                "execution_scope": "checks-only" if checks_only else "one-model-agentic-review" if mode in {"db", "endpoints"} else "two-model-agentic-review",
                "checks": checks, "agent_assessments": assessments,
                "review": {"passed": automation_passed, "checks_passed": checks_passed,
                           "meaning": "Automated execution status only; not human approval or proof of semantic correctness."},
                "human_decision": {"status": "pending", "reviewer": None, "decision": None, "rationale": None},
                "limitations": ["Citation and payload checks establish traceability, not semantic correctness of generated claims.",
                                "Architecture mode checks actual Student 2 Compose configuration and running containers; other modes alone do not establish Docker deployment. No mode proves all-feature group integration or browser UI behavior.",
                                "Legacy collectors cover Student 2 only; other student integration remains separately unverified.",
                                "Model assessments are advisory and use bounded excerpts; a human must verify claims against full evidence."],
                "improve": {"next_step": "A human reviews checks and required assessments, then records their own decision using human_review.py with before/after evidence links."}}
    return evidence


def run(mode: str, evidence_file: str | None = None, **options) -> int:
    if mode not in MODES:
        raise ValueError("Unsupported mode.")
    if mode in {"all", "release0"}:
        started = timestamp()
        selected = SINGLE_MODES if mode == "all" else LEGACY_MODES
        results = {key: capture_mode(key, **options) for key in selected}
        evidence = {"mode": mode, "feature": options.get("feature", "resume"), "started_at": started,
            "finished_at": timestamp(), "mode_results": results,
            "execution_scope": "checks-only" if options.get("checks_only") else "course-modes-agentic-review",
            "review": {"passed": all(item["review"]["passed"] for item in results.values()),
                       "checks_passed": all(item["review"]["checks_passed"] for item in results.values()),
                       "meaning": "Student 2 automated evidence only, not human approval or group completion."},
            "human_decision": {"status": "pending", "reviewer": None, "decision": None, "rationale": None}}
    else:
        evidence = capture_mode(mode, **options)
    rendered = json.dumps(evidence, indent=2, ensure_ascii=False)
    print(rendered)
    if evidence_file:
        path = Path(evidence_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if evidence["review"]["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture course DB/endpoints/architecture/DevOps/MCP/RAG checks and model assessments.")
    parser.add_argument("--mode", choices=sorted(MODES), default="all")
    parser.add_argument("--feature", choices=["resume", "interview"], default="resume")
    parser.add_argument("--profile-id", type=int, default=1)
    parser.add_argument("--resume-id", type=int, default=1)
    parser.add_argument("--target-role", default="Software Engineer")
    parser.add_argument("--query", help="Override the positive RAG query.")
    parser.add_argument("--job-description", default="Python API development, Docker, tests, and evidence of project outcomes.")
    parser.add_argument("--timeout", type=float, default=180, help="Per-request time limit, at most 600 seconds.")
    parser.add_argument("--checks-only", action="store_true", help="Deterministic diagnostics; not a full agentic review.")
    parser.add_argument("--evidence-file")
    parser.add_argument("--project-root", help="Defaults to the repository containing ai-services.")
    parser.add_argument("--compose-file", dest="compose_files", action="append", help="Repeat for a root Compose file and port overrides.")
    parser.add_argument("--compose-project", help="Running Compose project name; no containers are changed.")
    parser.add_argument("--ci-evidence-dir", help="Directory containing actual workflow artifacts and report.json.")
    args = parser.parse_args()
    if not 0 < args.timeout <= 600 or args.profile_id < 1 or args.resume_id < 1:
        parser.error("Use positive IDs and a timeout greater than 0 and at most 600 seconds.")
    sys.exit(run(**vars(args)))
