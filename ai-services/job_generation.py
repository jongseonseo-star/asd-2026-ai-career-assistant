"""Generate cited job guidance in the shared RAG process."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[1] / "student-4" / "backend"
_spec = importlib.util.spec_from_file_location("rag_job_contract", BACKEND_DIR / "job_contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


class GenerationError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        self.message = message
        self.status_code = status_code
        self.dependency = "ollama"


def generate(query: str, sources: list[dict]) -> tuple[dict, dict]:
    if os.getenv("OLLAMA_ENABLED", "true").lower() not in {"true", "1", "yes"}:
        raise GenerationError("Local model generation is disabled.")
    prompt = (BACKEND_DIR / "prompts" / "job_guidance.txt").read_text(encoding="utf-8")
    body = {
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"), "stream": False,
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": json.dumps({"question": query, "evidence_sources": sources})}],
        "format": contract.answer_schema(sources),
        "options": {"temperature": 0, "num_predict": 1000, "num_ctx": 8192},
    }
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    request = Request(base_url + "/api/chat", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))) as response:
            payload = json.load(response)
        if payload.get("done") is False or payload.get("done_reason") == "length":
            raise ValueError("The model response was incomplete.")
        result = json.loads(payload["message"]["content"])
        contract.validate_claims(result, sources)
    except (URLError, OSError, TimeoutError) as error:
        raise GenerationError("Local model generation failed or timed out.") from error
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise GenerationError("The model returned incomplete or invalid cited guidance.", 502) from error
    return result, {"called": True, "service": "shared-rag", "done_reason": payload.get("done_reason")}


def answer(payload: dict, retrieval: dict) -> dict:
    context = payload.get("job_context")
    contract.validate_context(context)
    sources = contract.evidence_sources(context, retrieval["results"])
    result = {
        "status": "insufficient-context", "answer": "Insufficient context: no relevant job guidance was found.",
        "claims": [], "evidence_sources": sources, "sources": [item["source"] for item in retrieval["results"]],
        "confidence": retrieval["confidence"], "confidence_basis": retrieval["confidence_basis"],
        "retrieval": retrieval, "model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
        "generation_metadata": {"called": False, "service": "shared-rag"},
    }
    if retrieval["results"]:
        generated, metadata = generate(payload["query"], sources)
        result.update(status="answered", claims=generated["claims"], generation_metadata=metadata,
                      answer="\n".join(claim["text"] for claim in generated["claims"]))
    contract.validate_answer(result, context)
    return result
