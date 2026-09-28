from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


MODES = {"release0", "mcp", "rag", "all"}
MCP_URL = os.getenv("MCP_BASE_URL", "http://127.0.0.1:8765")


def check(url: str, payload: dict | None = None) -> dict:
    request = Request(url, method="POST" if payload is not None else "GET")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.data = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(request, timeout=5) as response:
            return {"url": url, "status": response.status, "payload": json.loads(response.read())}
    except (OSError, URLError) as error:
        return {"url": url, "status": 503, "error": str(error)}


async def check_mcp() -> dict:
    try:
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            result = await client.call_tool("interview_context", {"target_role": "Software Engineer"})
        return {"protocol": "MCP", "status": 200, "tools": len(tools), "has_result": bool(result.content)}
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        return {"protocol": "MCP", "status": 503, "error": str(error)}


def run(mode: str, evidence_file: str | None = None) -> int:
    checks = []
    if mode in {"release0", "all"}:
        checks.append(check("http://127.0.0.1:11434/api/tags"))
    if mode in {"mcp", "all"}:
        checks.append(asyncio.run(check_mcp()))
    if mode in {"rag", "all"}:
        checks.extend([
            check("http://127.0.0.1:8766/health"),
            check("http://127.0.0.1:8766/retrieve", {"query": "API interview trade-offs"}),
            check("http://127.0.0.1:8766/pipeline", {"query": "API interview trade-offs"}),
        ])
    evidence = {
        "mode": mode,
        "workflow": ["DESIGN", "IMPLEMENT", "EXECUTE", "CAPTURE EVIDENCE", "REVIEW", "IMPROVE"],
        "checks": checks,
        "review": {"passed": all(item["status"] == 200 for item in checks)},
        "improve": {"next_step": "Refresh the RAG corpus or add MCP tools when a check fails."},
    }
    rendered = json.dumps(evidence, indent=2)
    print(rendered)
    if evidence_file:
        path = Path(evidence_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if evidence["review"]["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate local Release 0, MCP, and RAG modes.")
    parser.add_argument("--mode", choices=sorted(MODES), default="all")
    parser.add_argument("--evidence-file", help="Write validation evidence JSON to this path.")
    args = parser.parse_args()
    sys.exit(run(args.mode, args.evidence_file))
