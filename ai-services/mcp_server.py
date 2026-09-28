from __future__ import annotations

import argparse
import json
import os
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastmcp import FastMCP
from fastmcp.exceptions import ValidationError
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult
from pydantic import Field


def tool_error(message: str, status_code: int) -> ToolResult:
    """Keep domain status in structuredContent and mark the MCP call as failed."""
    return ToolResult(
        structured_content={"error": message, "status_code": status_code},
        is_error=True,
    )


class BoundedToolInputErrors(Middleware):
    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except ValidationError:
            if context.message.name == "resume_context":
                return tool_error("Provide only profile_id and resume_id as positive integers.", 400)
            if context.message.name in {"refresh_corpus", "retrieve_context", "answer_question"}:
                return tool_error("Tool arguments must match the declared feature, query, ID and top_k limits.", 400)
            raise


mcp = FastMCP("shared-career-assistant", middleware=[BoundedToolInputErrors()])
DATABASE_API_URL = os.getenv("STUDENT2_DATABASE_API_URL", "http://127.0.0.1:5002").rstrip("/")
DATABASE_TIMEOUT = float(os.getenv("DATABASE_TIMEOUT_SECONDS", "5"))
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://127.0.0.1:8766").rstrip("/")
RAG_TIMEOUT = float(os.getenv("RAG_TIMEOUT_SECONDS", "210"))


def database_get(path: str):
    """Read candidate records through their owning database service's HTTP API."""
    try:
        with urlopen(f"{DATABASE_API_URL}{path}", timeout=DATABASE_TIMEOUT) as response:
            return json.load(response), response.status
    except HTTPError as error:
        status = error.code if error.code in {400, 404} else 503
        return {"error": "Candidate record was not found." if status == 404 else "Candidate database request failed."}, status
    except (URLError, TimeoutError, OSError, ValueError):
        return {"error": "Candidate database service is unavailable or returned invalid data."}, 503


@mcp.tool()
def resume_context(
    profile_id: Annotated[int, Field(strict=True, ge=1)],
    resume_id: Annotated[int, Field(strict=True, ge=1)],
) -> ToolResult:
    """Fetch current profile, owned resume and skills from the Student 2 database API."""
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (profile_id, resume_id)):
        return tool_error("profile_id and resume_id must be positive integers.", 400)
    profile, status = database_get(f"/api/v1/profiles/{profile_id}")
    if status != 200:
        return tool_error(profile["error"], status)
    resume, status = database_get(f"/api/v1/resumes/{resume_id}")
    if status != 200:
        return tool_error(resume["error"], status)
    if not isinstance(profile, dict) or profile.get("id") != profile_id or not isinstance(resume, dict) or resume.get("id") != resume_id:
        return tool_error("Candidate database returned invalid record data.", 502)
    if resume.get("candidate_profile_id") != profile_id:
        return tool_error("The selected resume does not belong to the selected candidate profile.", 400)
    skills, status = database_get(f"/api/v1/skills?candidate_profile_id={profile_id}")
    if status != 200:
        return tool_error(skills["error"], status)
    if not isinstance(skills, list) or any(not isinstance(skill, dict) or skill.get("candidate_profile_id") != profile_id for skill in skills):
        return tool_error("Candidate database returned invalid skill data.", 502)
    return ToolResult(structured_content={
        "candidate_profile": profile,
        "resume": resume,
        "candidate_skills": skills,
        "sources": [f"db://student-2/profiles/{profile_id}", f"db://student-2/resumes/{resume_id}"]
        + [f"db://student-2/skills/{skill['id']}" for skill in skills if isinstance(skill.get("id"), int)],
    })


@mcp.tool()
def interview_context(target_role: str, interview_type: str = "general") -> dict[str, object]:
    """Build structured interview context for a target role and interview type."""
    role = target_role.strip() or "General role"
    interview_type = interview_type.strip() or "general"
    return {
        "target_role": role,
        "interview_type": interview_type,
        "evaluation_dimensions": ["technical accuracy", "clarity", "evidence", "trade-offs"],
        "question_guidance": f"Ask practical {interview_type} questions for a {role} candidate.",
    }


def rag_request(path: str, payload: dict) -> ToolResult:
    """Forward only the three declared operations to the configured shared RAG."""
    if path not in {"/refresh", "/retrieve", "/answer"}:
        return tool_error("Unsupported shared RAG operation.", 400)
    request = Request(RAG_BASE_URL + path, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=RAG_TIMEOUT) as response:
            result = json.load(response)
    except HTTPError as error:
        status = error.code if error.code in {400, 404, 502, 503} else 503
        return tool_error("Shared RAG request failed. Check the query, selected records and approved corpus.", status)
    except (URLError, TimeoutError, OSError):
        return tool_error("Shared RAG service is unavailable or timed out.", 503)
    except (ValueError, TypeError):
        return tool_error("Shared RAG returned invalid JSON.", 502)
    if not isinstance(result, dict) or result.get("error"):
        return tool_error("Shared RAG returned an invalid operation result.", 502)
    if path == "/refresh":
        valid = result.get("status") == "success" and isinstance(result.get("corpora"), list) and bool(result["corpora"])
    elif path == "/retrieve":
        valid = isinstance(result.get("results"), list) and result.get("confidence") in ("low", "medium", "high")
    else:
        valid = (result.get("status") in ("answered", "insufficient-context")
                 and isinstance(result.get("feedback"), str) and bool(result["feedback"].strip())
                 and result.get("confidence") in ("low", "medium", "high"))
    if not valid:
        return tool_error("Shared RAG returned an incomplete operation result.", 502)
    return ToolResult(structured_content=result)


@mcp.tool()
def refresh_corpus(feature: Literal["resume", "interview"] = "resume") -> ToolResult:
    """Refresh one approved local corpus; no arbitrary file paths or sources are accepted."""
    return rag_request("/refresh", {"feature": feature})


@mcp.tool()
def retrieve_context(
    query: Annotated[str, Field(min_length=1, max_length=20000)],
    top_k: Annotated[int, Field(strict=True, ge=1, le=5)] = 3,
    feature: Literal["resume", "interview"] = "resume",
) -> ToolResult:
    """Retrieve cited context from an approved corpus through the shared RAG service."""
    if not query.strip():
        return tool_error("query must contain non-whitespace text.", 400)
    return rag_request("/retrieve", {"query": query.strip(), "top_k": top_k, "feature": feature})


@mcp.tool()
def answer_question(
    profile_id: Annotated[int, Field(strict=True, ge=1)],
    resume_id: Annotated[int, Field(strict=True, ge=1)],
    query: Annotated[str, Field(min_length=1, max_length=20000)],
    top_k: Annotated[int, Field(strict=True, ge=1, le=5)] = 3,
    job_description: Annotated[str, Field(max_length=6000)] = "",
) -> ToolResult:
    """Generate grounded resume feedback using owned DB records and shared RAG; never accepts caller-supplied context."""
    if not query.strip():
        return tool_error("query must contain non-whitespace text.", 400)
    context = resume_context(profile_id, resume_id)
    if context.is_error:
        return context
    return rag_request("/answer", {"task": "resume-feedback", "feature": "resume",
        "query": query.strip(), "top_k": top_k, "candidate_context": context.structured_content,
        "job_description": job_description})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the shared local MCP server.")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="streamable-http")
    args = parser.parse_args()
    mcp.run(
        transport=args.transport,
        host=os.getenv("AI_SERVICES_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8765")),
    )
