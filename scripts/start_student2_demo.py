#!/usr/bin/env python3
"""Start the existing Student 2 demo services; keep this terminal open.

Run with the project's virtual-environment Python from a normal host terminal.
This checks connectivity and retrieval, not generated answers or human approval.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"mcp": 18765, "rag": 18766, "multi-agent": 18767}
MODELS = {"qwen2.5:7b", "llama3.1:8b"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def http(url: str, body=None, timeout: float = 20, raw: bool = False):
    request = Request(url, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read(1500).decode("utf-8", errors="replace")
        raise RuntimeError(f"{url}: HTTP {error.code}: {detail}") from error
    return text if raw else json.loads(text)


class Demo:
    def __init__(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.directory = ROOT / "reports" / "demo-runtime" / f"{stamp}-{os.getpid()}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.children = []
        self.logs = []
        self.state = {"status": "starting", "started_at": now(), "source_root": str(ROOT),
                      "report_directory": str(self.directory), "ports": PORTS, "checks": {},
                      "model_workflow_verified": False, "human_review_recorded": False}
        self.update()

    def update(self, **values):
        self.state.update(values)
        self.state["updated_at"] = now()
        temporary = self.directory / "status.tmp"
        temporary.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.directory / "status.json")

    def check(self, name, result):
        self.state["checks"][name] = result
        self.update()
        print(f"OK: {name}", flush=True)

    def command(self, name, arguments, env=None, timeout=60):
        print(f"Running {name}; log: {self.directory / (name + '.log')}", flush=True)
        if name == "compose-build":
            print("Building the four selected containers may take several minutes. "
                  "Progress is written continuously to the log above.", flush=True)
        with (self.directory / f"{name}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(arguments, cwd=ROOT, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit {result.returncode}; see {name}.log")

    def alive(self):
        for name, process in self.children:
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited with code {process.returncode}; see {name}.log")

    def wait_for(self, label, operation, timeout=90):
        deadline, last_error = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            self.alive()
            try:
                return operation()
            except Exception as error:
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"{label} was not ready within {timeout}s: {last_error}")

    def start(self, name, script, env, arguments=()):
        log = (self.directory / f"{name}.log").open("w", encoding="utf-8")
        self.logs.append(log)
        process = subprocess.Popen([sys.executable, "-B", "-u", str(ROOT / script), *arguments],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        self.children.append((name, process))

    def stop(self):
        # Every stored process was created above in its own process group.
        for _, process in self.children:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 5
        for _, process in self.children:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        for log in self.logs:
            log.close()

    async def mcp_check(self, profile_id, resume_id):
        from fastmcp import Client

        async with Client("http://127.0.0.1:18765/mcp", timeout=20) as client:
            tools = await client.list_tools()
            names = [tool.name for tool in tools]
            if "resume_context" not in names:
                raise RuntimeError("MCP resume_context tool is missing.")
            result = await client.call_tool("resume_context", arguments={
                "profile_id": profile_id, "resume_id": resume_id}, raise_on_error=False)
        context = getattr(result, "structured_content", None)
        if (getattr(result, "is_error", True) or not isinstance(context, dict)
                or context.get("candidate_profile", {}).get("id") != profile_id
                or context.get("resume", {}).get("id") != resume_id):
            raise RuntimeError("MCP could not retrieve the selected matching candidate and resume.")
        return {"tool_names": names, "profile_id": profile_id, "resume_id": resume_id,
                "skill_count": len(context.get("candidate_skills", []))}

    def run(self):
        print(f"Runtime logs: {self.directory}", flush=True)
        for name, port in PORTS.items():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as error:
                    raise RuntimeError(f"Cannot reserve {name} port {port}: {error}. "
                                       "Identify its owner; this launcher will not stop it.") from error
        for package in ("flask", "fastmcp", "chromadb", "yaml"):
            if importlib.util.find_spec(package) is None:
                raise RuntimeError(f"Missing Python dependency: {package}. Run the bootstrap first.")
        self.command("docker-info", ["docker", "info", "--format", "{{.ServerVersion}}"])
        tags = http("http://127.0.0.1:11434/api/tags")
        installed = {item.get("name") for item in tags.get("models", [])}
        missing = MODELS - installed
        if missing:
            raise RuntimeError(f"Ollama models not installed: {', '.join(sorted(missing))}")
        self.check("prerequisites", {"models": sorted(MODELS), "ports_available": True})

        common = dict(os.environ, AI_SERVICES_HOST="127.0.0.1", OLLAMA_ENABLED="true",
                      OLLAMA_BASE_URL="http://127.0.0.1:11434", OLLAMA_MODEL="llama3.1:8b",
                      OLLAMA_NUM_CTX="8192", OLLAMA_TIMEOUT_SECONDS="180")
        self.start("rag", "ai-services/rag_server.py", dict(common, RAG_PORT="18766"))
        self.start("mcp", "ai-services/mcp_server.py", dict(common, MCP_PORT="18765",
                   STUDENT2_DATABASE_API_URL="http://127.0.0.1:5002",
                   RAG_BASE_URL="http://127.0.0.1:18766", RAG_TIMEOUT_SECONDS="210"),
                   ("--transport", "streamable-http"))
        self.start("multi-agent", "ai-services/multi_agent_server.py", dict(common,
                   MULTI_AGENT_PORT="18767", OLLAMA_TIMEOUT_SECONDS="90",
                   PLANNER_MODEL="qwen2.5:7b", WORKER_MODEL="qwen2.5:7b",
                   REVIEWER_MODEL="llama3.1:8b"), ("--serve", "--port", "18767"))
        for name in ("rag", "multi-agent"):
            result = self.wait_for(name, lambda n=name: http(f"http://127.0.0.1:{PORTS[n]}/health", timeout=3))
            self.check(f"{name}-health", result)
        refreshed = http("http://127.0.0.1:18766/refresh", {"feature": "resume"}, timeout=90)
        if refreshed.get("status") != "success":
            raise RuntimeError("RAG corpus refresh did not report success.")
        retrieval = http("http://127.0.0.1:18766/retrieve", {
            "query": "resume achievements and skill evidence", "feature": "resume", "top_k": 3})
        (self.directory / "rag-retrieval.json").write_text(
            json.dumps(retrieval, indent=2) + "\n", encoding="utf-8")
        if (not retrieval.get("results") or retrieval.get("retrieval_mode") != "vector"
                or retrieval.get("vector_store_status") != "ready"):
            raise RuntimeError("RAG did not return successful vector retrieval with resume guidance.")
        self.check("rag-vector-retrieval", {"result_count": len(retrieval["results"]), "refresh": refreshed})

        compose_env = dict(os.environ, AI_SERVICES_ENABLED="true", OLLAMA_ENABLED="true",
                           MULTI_AGENT_ENABLED="true", OLLAMA_MODEL="llama3.1:8b",
                           MCP_BASE_URL="http://host.docker.internal:18765",
                           RAG_BASE_URL="http://host.docker.internal:18766",
                           MULTI_AGENT_SERVER_URL="http://host.docker.internal:18767",
                           MULTI_AGENT_TIMEOUT_SECONDS="360", AI_TIMEOUT_SECONDS="420",
                           RAG_GENERATION_TIMEOUT_SECONDS="210")
        compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"),
                   "-p", "asd-2026-ai-career-assistant"]
        self.command("compose-build", [*compose, "up", "--build", "-d", "--no-deps",
                     "student-2-database", "student-2-backend", "student-2-frontend", "shared-frontend"],
                     env=compose_env, timeout=1200)
        self.command("compose-ps", [*compose, "ps"], env=compose_env)
        for label, port, route in (("database", 5002, "health"), ("backend", 5001, "ready"),
                                   ("frontend", 8082, "ready")):
            self.check(f"{label}-ready", self.wait_for(label,
                lambda p=port, r=route: http(f"http://127.0.0.1:{p}/{r}", timeout=5)))
        container_probe = (
            "import json, os, urllib.request\n"
            "for key in ('RAG_BASE_URL', 'MULTI_AGENT_SERVER_URL'):\n"
            "    with urllib.request.urlopen(os.environ[key] + '/health', timeout=10) as response:\n"
            "        result = json.load(response)\n"
            "    assert result.get('status') == 'healthy', (key, result)\n"
            "    print(key, json.dumps(result))\n"
        )
        self.command("container-ai-health", [*compose, "exec", "-T", "student-2-backend",
                     "python", "-c", container_probe], env=compose_env)
        self.check("container-to-rag-and-multi-agent", {"health": "passed"})
        options = http("http://127.0.0.1:8082/ui/multi-agent/options")
        ids = {profile["id"] for profile in options.get("profiles", [])}
        resume = next((item for item in options.get("resumes", [])
                       if item.get("candidate_profile_id") in ids), None)
        if resume is None:
            raise RuntimeError("No matching candidate/resume exists; create demo records in the UI.")
        profile_id, resume_id = resume["candidate_profile_id"], resume["id"]
        self.check("mcp-protocol", asyncio.run(self.mcp_check(profile_id, resume_id)))
        via_backend = http("http://127.0.0.1:5001/api/v1/ai/resume-feedback", {
            "profile_id": profile_id, "resume_id": resume_id, "mode": "mcp"}, timeout=45)
        if via_backend.get("status") != "context-only":
            raise RuntimeError("Backend-to-MCP context check failed.")
        self.check("backend-to-mcp", {"status": "context-only", "profile_id": profile_id, "resume_id": resume_id})
        ai = http("http://127.0.0.1:5001/api/v1/ai/status")
        if ai.get("configured_model_available") is not True or ai.get("shared_ai_enabled") is not True:
            raise RuntimeError("Backend local model or shared AI configuration is unavailable.")
        self.check("backend-to-ollama", ai)
        if "Multi-Agent Review" not in http("http://127.0.0.1:8082/", raw=True):
            raise RuntimeError("The frontend is missing the new Multi-Agent Review tab.")
        self.check("frontend-options", {"profile_id": profile_id, "resume_id": resume_id, "new_tab": True})
        self.update(status="ready_for_ui_verification")
        print("STATUS: ready_for_ui_verification\n"
              "Open http://127.0.0.1:8082 and run AI/RAG and Multi-Agent Review.\n"
              "Model generation and human review have NOT yet been verified.\n"
              "Keep this terminal open. Ctrl+C stops only these three AI servers; containers/data remain.", flush=True)
        while True:
            self.alive()
            time.sleep(1)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    demo = Demo()

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        demo.run()
    except KeyboardInterrupt:
        demo.update(status="stopped", previous_status=demo.state["status"])
        print("Stopping this launcher's AI services; containers/data are unchanged.", flush=True)
        return 0
    except Exception as error:
        demo.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(f"FAILED: {error}\nReports: {demo.directory}", file=sys.stderr, flush=True)
        return 1
    finally:
        demo.stop()


if __name__ == "__main__":
    raise SystemExit(main())
