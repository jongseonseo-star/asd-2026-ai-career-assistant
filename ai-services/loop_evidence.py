"""Prompt preparation with intact candidate facts and claim-to-source mappings."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def legacy_payload(payload):
    """Keep observed domain facts, not repeated prose or copies of records/config."""
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        return {"record_count": len(payload), "object_rows": len(rows),
                "observed_fields": sorted({key for row in rows for key in row}),
                "sample_record_ids": [row.get("id") for row in rows[:3]],
                "unique_profile_owner_ids": sorted({row["candidate_profile_id"] for row in rows
                    if type(row.get("candidate_profile_id")) is int})}
    if not isinstance(payload, dict):
        return payload
    if "samples" in payload:
        samples = payload["samples"]
        return {key: value for key, value in payload.items() if key != "samples"} | {
            "sample_count": len(samples), "durations_ms": [round(row["duration_seconds"] * 1000, 3) for row in samples],
            "successful_samples": sum(row.get("passed") is True for row in samples)}
    if "student2_services" in payload:
        services = {}
        for name, value in payload["student2_services"].items():
            if not isinstance(value, dict):
                services[name] = None
                continue
            services[name] = {"build_context": value.get("build", {}).get("context") if isinstance(value.get("build"), dict) else value.get("build"),
                "api_urls": {key: url for key, url in value.get("environment", {}).items() if key.endswith("_URL")},
                "depends_on": list(value.get("depends_on", {})), "ports": value.get("ports", []),
                "volumes": value.get("volumes", [])}
        return {"scope": payload["scope"], "compose_project": payload.get("compose_project"),
                "services": services, "containers": [{key: row.get(key) for key in ("Service", "State", "Health")} for row in payload.get("containers", [])],
                "verified_source_files": sorted(payload.get("file_sha256", {}))}
    if "artifacts" in payload:
        report = payload["artifacts"].get("report.json", {})
        report = report if isinstance(report, dict) else {}
        workflow = payload.get("workflow", {})
        workflow = workflow if isinstance(workflow, dict) else {}
        return {"scope": payload.get("scope"), "workflow": {"name": workflow.get("name"), "triggers": workflow.get("triggers"),
                "job_names": workflow.get("job_names"), "step_names_in_order": [step.get("name") for step in workflow.get("steps", [])]},
                "actual_run": {key: report[key] for key in ("execution_source", "job_status", "record_counts", "ai_services_enabled", "ollama_enabled", "run_url", "commit_sha") if key in report},
                "workflow_hash_matches": report.get("workflow_sha256") == workflow.get("sha256"),
                "saved_artifact_names": sorted(payload["artifacts"]),
                "recorded_stages": [{key: stage.get(key) for key in ("name", "status", "return_code") if key in stage}
                                    for stage in (report.get("stages") or []) if isinstance(stage, dict)],
                "github_run_proven": payload.get("github_run_proven")}
    return payload


def assessment_evidence(mode, feature, checks):
    if mode in {"db", "endpoints", "architecture", "devops"}:
        return {"mode": mode, "feature": feature, "checks_sha256": digest(checks),
            "scope": "Only the named Student 2 checks were observed. Passed means the listed deterministic check passed, not overall application approval. Assess a concrete observed fact; if no defect is shown, say no defect observed within this scope.",
            "checks": [{"name": item.get("name"), "passed": item["passed"], "status": item.get("status"),
                "validation_errors": item.get("validation_errors", []),
                "observed": legacy_payload(item.get("payload", item.get("error")))} for item in checks]}
    observed, documents, candidates = [], {}, []
    excerpt_limit = max(600, 8000 // max(len(checks), 1))
    for index, item in enumerate(checks):
        payload = item.get("payload")
        request = item.get("request", {})
        body = request.get("body")
        summary = {key: value for key, value in request.items() if key != "body"}
        if isinstance(body, dict):
            summary["body"] = {key: body[key][:1200] if isinstance(body[key], str) else body[key]
                               for key in ("task", "query", "feature", "top_k") if key in body}
            summary["query_truncated"] = isinstance(body.get("query"), str) and len(body["query"]) > 1200
        entry = {"name": item.get("name", "unnamed-check"), "check_index": index, "passed": item["passed"],
                 "status": item.get("status"), "validation_errors": item.get("validation_errors", []), "request": summary}
        context = payload if isinstance(payload, dict) and "candidate_profile" in payload else body.get("candidate_context") if isinstance(body, dict) else None
        if isinstance(context, dict):
            candidate = {key: context[key] for key in ("candidate_profile", "resume", "candidate_skills", "sources") if key in context}
            if candidate not in candidates:
                candidates.append(candidate)
            entry["candidate_context_index"] = candidates.index(candidate)
        if isinstance(payload, dict) and "feedback_sections" in payload:
            source_map = {}
            for source in payload.get("evidence_sources", []):
                if not isinstance(source, dict):
                    continue
                key = digest({field: source.get(field) for field in ("source", "text", "kind")})
                documents[key] = {field: source.get(field) for field in ("source", "text", "kind")}
                source_map[source.get("id", "<missing-id>")] = key
            # Complete claims and IDs remain together; never cut a JSON string mid-mapping.
            entry["answer"] = {"status": payload.get("status"), "claims_by_section": payload.get("feedback_sections"),
                "citation_id_to_document": source_map, "confidence": payload.get("confidence"),
                "confidence_basis": payload.get("confidence_basis"), "generation_metadata": payload.get("generation_metadata")}
            entry["result_truncated"] = False
        elif isinstance(context, dict):
            entry["result_truncated"] = False
            entry["registered_tools"] = item.get("registered_tools", [])
        else:
            # Non-semantic execution detail is bounded, with full records retained separately.
            if isinstance(payload, list):
                data = {"record_count": len(payload), "sample_records": payload[:2], "sample_is_partial": len(payload) > 2}
            elif isinstance(payload, dict) and "artifacts" in payload:
                data = {"workflow": payload.get("workflow"), "report": payload["artifacts"].get("report.json"),
                        "artifact_sha256": payload.get("artifact_sha256"), "github_run_proven": payload.get("github_run_proven")}
                if isinstance(data["workflow"], dict):
                    data["workflow"] = {key: value for key, value in data["workflow"].items() if key != "steps"}
            elif isinstance(payload, dict) and "samples" in payload:
                data = {key: value for key, value in payload.items() if key != "samples"}
            else:
                data = payload if payload is not None else item.get("error")
            text = json.dumps(data, ensure_ascii=False)
            entry.update(result_excerpt=text[:excerpt_limit], result_truncated=len(text) > excerpt_limit)
        observed.append(entry)
    return {"mode": mode, "feature": feature, "checks_sha256": digest(checks),
            "scope": "Actual observations. Complete candidate contexts and per-claim citation mappings are preserved. Other execution detail may be excerpted; full checks are saved separately.",
            "candidate_contexts": candidates, "documents_by_hash": documents, "checks": observed}
