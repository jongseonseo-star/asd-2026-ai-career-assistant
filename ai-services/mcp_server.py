from __future__ import annotations

import argparse
import os

from fastmcp import FastMCP

mcp = FastMCP("shared-career-assistant")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the shared local MCP server.")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="streamable-http")
    args = parser.parse_args()
    mcp.run(
        transport=args.transport,
        host="127.0.0.1",
        port=int(os.getenv("MCP_PORT", "8765")),
    )
