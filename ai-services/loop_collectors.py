"""Small, read-only collectors for the four Release 0 course review modes.

DB evidence comes from the owning database service, never a copied seed file.
Architecture checks only Student 2; they cannot certify group integration.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


RESOURCES = ("profiles", "resumes", "skills")
SERVICES = tuple(f"student-2-{part}" for part in ("frontend", "backend", "database"))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def recorded(name, payload, errors, started=None):
    return {"name": name, "payload": payload, "passed": not errors,
            "validation_errors": errors, "finished_at": stamp(),
            "duration_seconds": round(time.monotonic() - started, 3) if started else 0}


def valid_rows(payload, resource):
    if not isinstance(payload, list) or len(payload) < 10:
        return [f"{resource}: expected at least ten actual records."]
    fields = {"profiles": ("full_name", "email", "target_role", "career_summary"),
              "resumes": ("title", "content"), "skills": ("skill_name", "proficiency_level")}[resource]
    errors, ids = [], set()
    for row in payload:
        if not isinstance(row, dict):
            errors.append(f"{resource}: record must be an object.")
            continue
        record_id = row.get("id")
        if type(record_id) is not int or record_id < 1 or record_id in ids:
            errors.append(f"{resource}: IDs must be unique positive integers.")
        else:
            ids.add(record_id)
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in fields):
            errors.append(f"{resource}: required text is missing.")
        if resource != "profiles" and (type(row.get("candidate_profile_id")) is not int or row["candidate_profile_id"] < 1):
            errors.append(f"{resource}: candidate ownership is missing.")
    return sorted(set(errors))


def validate_relations(records):
    errors = []
    for resource in RESOURCES:
        errors.extend(valid_rows(records.get(resource), resource))
    if errors:
        return errors
    profile_ids = {row["id"] for row in records["profiles"]}
    for resource in ("resumes", "skills"):
        if any(row["candidate_profile_id"] not in profile_ids for row in records[resource]):
            errors.append(f"{resource}: orphaned candidate reference in live data.")
    return errors


def healthy(payload):
    return [] if isinstance(payload, dict) and payload.get("status") in ("healthy", "ready") else ["Service did not report healthy/ready."]


def collect_db(check, bases, timeout):
    checks = [check(bases["database"] + "/health", name="db-health", validator=healthy, timeout=timeout)]
    records = {}
    for resource in RESOURCES:
        result = check(bases["database"] + "/api/v1/" + resource, name="db-" + resource,
                       validator=lambda data, resource=resource: valid_rows(data, resource), timeout=timeout)
        checks.append(result)
        records[resource] = result.get("payload")
    checks.append(recorded("db-live-relations", {"record_counts": {
        key: len(value) if isinstance(value, list) else None for key, value in records.items()},
        "scope": "Records read from the running Student 2 database API; no direct file access."}, validate_relations(records)))
    return checks


def collect_endpoints(check, bases, timeout):
    checks = [check(bases["backend"] + "/ready", name="backend-ready", validator=healthy, timeout=timeout),
              check(bases["frontend"] + "/ready", name="frontend-ready", validator=healthy, timeout=timeout)]
    for resource in RESOURCES:
        result = check(bases["backend"] + "/api/v1/" + resource, name="endpoint-" + resource,
                       validator=lambda data, resource=resource: valid_rows(data, resource), timeout=timeout)
        database = check(bases["database"] + "/api/v1/" + resource, name="endpoint-db-" + resource,
                         validator=lambda data, resource=resource: valid_rows(data, resource), timeout=timeout)
        checks.extend((result, database))
        same = result["passed"] and database["passed"] and result["payload"] == database["payload"]
        checks.append(recorded("endpoint-proxy-" + resource, {"backend_matches_database": same},
                               [] if same else ["Backend and owning database do not expose the same records."]))
    # Deliberately invalid input is rejected before any database write.
    checks.append(check(bases["backend"] + "/api/v1/profiles", {}, name="endpoint-input-boundary",
                        expected_status=400, validator=lambda p: [] if isinstance(p, dict) and p.get("error") else ["Expected structured rejection."], timeout=timeout))
    samples = [check(bases["backend"] + "/api/v1/profiles", name=f"latency-{i + 1}",
                     validator=lambda p: valid_rows(p, "profiles"), timeout=timeout) for i in range(20)]
    timely = sum(item["passed"] and item["duration_seconds"] <= .5 for item in samples)
    checks.append(recorded("endpoint-nfr-20-samples", {"target_ms": 500, "required": 19,
        "within_target": timely, "samples": samples, "scope": "GET profiles only; excludes AI generation."},
        [] if timely >= 19 else ["Fewer than 19 of 20 valid GET responses completed within 500 ms."]))
    return checks


def command(args, root, timeout):
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError(f"Command failed ({result.returncode}): {result.stderr[:2000]}")
    return result.stdout


def collect_architecture(root, compose_files, project, timeout):
    started = time.monotonic()
    payload = {"scope": "Student 2 frontend/backend/database only; not whole-group integration.",
               "compose_project": project, "compose_files": [str(p) for p in compose_files]}
    errors = []
    args = ["docker", "compose", "-p", project]
    for path in compose_files:
        args.extend(["-f", str(path)])
    try:
        config = json.loads(command(args + ["config", "--format", "json"], root, timeout))
        services = config.get("services", {})
        payload["student2_services"] = {key: services.get(key) for key in SERVICES}
        payload["all_declared_service_names"] = sorted(services)
        for name in SERVICES:
            if not isinstance(services.get(name), dict):
                errors.append(f"Missing Compose service {name}.")
        if any(name in services for name in ("ollama", "mcp", "rag", "agentic-loop", "mcp-server", "rag-server", "ai-services")):
            errors.append("AI/MCP/RAG/loop must run outside Compose.")
        for service, variable, target in (("student-2-frontend", "BACKEND_API_URL", "student-2-backend"),
                                           ("student-2-backend", "DATABASE_API_URL", "student-2-database")):
            value = services.get(service, {}).get("environment", {}).get(variable, "")
            if target not in value:
                errors.append(f"{service} does not use the owning {target} API.")
        backend_env = services.get("student-2-backend", {}).get("environment", {})
        for key in ("MCP_BASE_URL", "RAG_BASE_URL", "OLLAMA_BASE_URL"):
            if "host.docker.internal" not in str(backend_env.get(key, "")):
                errors.append(f"{key} does not point to the host local service.")
        raw = command(args + ["ps", "--all", "--format", "json"], root, timeout)
        containers = json.loads(raw) if raw.strip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]
        if isinstance(containers, dict):
            containers = [containers]
        payload["containers"] = [row for row in containers if row.get("Service") in SERVICES]
        for name in SERVICES:
            matching = [row for row in containers if row.get("Service") == name]
            if not matching or any(row.get("State") != "running" or row.get("Health") in {"unhealthy", "starting"} for row in matching):
                errors.append(f"{name} is not running and ready in the requested Compose project.")
        paths = [root / "student-2" / part / "app.py" for part in ("frontend", "backend", "database")]
        paths += list(compose_files)
        payload["file_sha256"] = {str(path.relative_to(root)) if path.is_relative_to(root) else str(path):
                                  hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        errors.append(f"Architecture evidence unavailable: {error}")
    return [recorded("architecture-compose-live", payload, errors, started)]


def collect_devops(root, evidence_dir):
    """Validate actual artifacts; local equivalents never become GitHub run proof."""
    import yaml

    started = time.monotonic()
    errors, payload = [], {"evidence_directory": str(evidence_dir), "scope": "Student 2 workflow only."}
    workflow = root / ".github/workflows/student-2.yml"
    try:
        workflow_text = workflow.read_text(encoding="utf-8")
        config = yaml.safe_load(workflow_text)
        triggers = config.get("on", config.get(True, {}))
        jobs = config.get("jobs", {})
        steps = [step for job in jobs.values() for step in job.get("steps", [])]
        payload["workflow"] = {"path": str(workflow), "sha256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
            "name": config.get("name"), "triggers": triggers, "job_names": list(jobs),
            "steps": [{key: step[key] for key in ("name", "if", "uses", "run") if key in step} for step in steps]}
        if not isinstance(triggers, dict) or "workflow_dispatch" not in triggers:
            errors.append("Workflow has no manual workflow_dispatch trigger.")
        job_envs = [job.get("env", {}) for job in jobs.values()]
        if not job_envs or any(str(env.get(key, "")).lower() != "false" for env in job_envs for key in ("AI_SERVICES_ENABLED", "OLLAMA_ENABLED")):
            errors.append("Workflow must explicitly disable AI and shared MCP/RAG during validation.")
        actions = "\n".join(str(step.get("run", "")) for step in steps)
        for token in ("build", "up -d", "curl", "report.json"):
            if token not in actions:
                errors.append(f"Workflow is missing build/smoke/evidence operation: {token}.")
        if not any("down" in str(step.get("run", "")) and "always()" in str(step.get("if", "")) for step in steps):
            errors.append("Workflow has no always-run Compose teardown.")
        if not any(str(step.get("uses", "")).startswith("actions/upload-artifact@") for step in steps):
            errors.append("Workflow has no artifact upload step.")
        filenames = ("report.json", "profiles.json", "resumes.json", "skills.json", "database-health.json",
                     "backend-readiness.json", "frontend-readiness.json", "ai-status.json", "compose-ps.txt", "compose-logs.txt")
        files = {}
        for name in filenames:
            path = evidence_dir / name
            if not path.is_file() or not path.stat().st_size:
                errors.append(f"Missing or empty actual CI artifact: {name}.")
                continue
            text = path.read_text(encoding="utf-8")
            files[name] = json.loads(text) if name.endswith(".json") else text
        payload["artifacts"] = files
        payload["artifact_sha256"] = {name: hashlib.sha256((evidence_dir / name).read_bytes()).hexdigest() for name in files}
        report = files.get("report.json", {})
        for key in ("execution_source", "job_status", "workflow", "generated_at_utc", "record_counts", "workflow_sha256"):
            if not report.get(key):
                errors.append(f"CI report missing {key}.")
        source = report.get("execution_source")
        if source not in {"github-actions", "local-ci-equivalent"}:
            errors.append("CI execution_source must identify GitHub Actions or a local equivalent.")
        payload["github_run_proven"] = False
        if source == "github-actions":
            for key in ("run_id", "run_url", "commit_sha"):
                if not report.get(key):
                    errors.append(f"GitHub artifact missing {key}.")
            if "/actions/runs/" not in str(report.get("run_url", "")):
                errors.append("GitHub run URL is invalid.")
        if report.get("job_status") != "success":
            errors.append("Actual CI execution did not succeed.")
        if report.get("workflow_sha256") != payload["workflow"]["sha256"]:
            errors.append("CI artifacts do not identify the current workflow bytes.")
        for key in ("ai_services_enabled", "ollama_enabled"):
            if report.get(key) is not False:
                errors.append(f"CI report must record {key}=false.")
        records = {resource: files.get(resource + ".json") for resource in RESOURCES}
        errors.extend(validate_relations(records))
        for resource, rows in records.items():
            if isinstance(rows, list) and report.get("record_counts", {}).get(resource) != len(rows):
                errors.append(f"CI count differs from saved {resource} response.")
        for name in ("database-health.json", "backend-readiness.json", "frontend-readiness.json"):
            errors.extend(f"{name}: {error}" for error in healthy(files.get(name)))
        if "disabled" not in json.dumps(files.get("ai-status.json", {})).lower():
            errors.append("AI status artifact does not demonstrate disabled generation.")
        payload["github_run_proven"] = source == "github-actions" and not errors
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as error:
        errors.append(f"DevOps evidence unavailable or malformed: {error}")
    return [recorded("devops-workflow-and-artifacts", payload, errors, started)]
