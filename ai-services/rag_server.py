from __future__ import annotations

import os
import importlib.util
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

_resume_spec = importlib.util.spec_from_file_location("rag_resume_generation", Path(__file__).resolve().parent / "resume_generation.py")
resume_generation = importlib.util.module_from_spec(_resume_spec)
_resume_spec.loader.exec_module(resume_generation)

_retrieval_spec = importlib.util.spec_from_file_location("local_rag_retrieval", Path(__file__).resolve().parent / "rag_retrieval.py")
rag_retrieval = importlib.util.module_from_spec(_retrieval_spec)
_retrieval_spec.loader.exec_module(rag_retrieval)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024
PORT = int(os.getenv("RAG_PORT", "8766"))
KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge" / "resume"
CONFIDENCE_BASIS = rag_retrieval.CONFIDENCE_BASIS
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(Path(__file__).resolve().parent / "data" / "rag")))
_index = None

DOCUMENTS = [
    {
        "id": "interview-star",
        "title": "STAR interview responses",
        "text": "Strong behavioural answers explain the situation, task, action, and measurable result.",
        "source": "shared://interview/star-method",
        "feature": "interview",
    },
    {
        "id": "api-design",
        "title": "API design fundamentals",
        "text": "Good API answers discuss validation, error handling, observability, security, and performance trade-offs.",
        "source": "shared://interview/api-design",
        "feature": "interview",
    },
    {
        "id": "technical-communication",
        "title": "Technical communication",
        "text": "Clear interview answers state assumptions, compare alternatives, and justify a decision with evidence.",
        "source": "shared://interview/communication",
        "feature": "interview",
    },
]


def load_documents(feature: str = "interview") -> list[dict[str, Any]]:
    if feature == "interview":
        return DOCUMENTS
    documents = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if path.is_symlink() or not path.resolve().is_relative_to(KNOWLEDGE_DIR.resolve()):
            raise rag_retrieval.CorpusError("Knowledge sources must be regular files in the approved directory.")
        raw = path.read_text(encoding="utf-8").strip()
        title, _, body = raw.partition("\n")
        documents.append({
            "id": path.stem,
            "title": title.lstrip("# ").strip(),
            "text": body.strip(),
            "source": f"repo://ai-services/knowledge/resume/{path.name}",
            "feature": "resume",
            "authority_tier": "tier_3",
            "provenance": "Project-authored guidance, not candidate evidence or an external authority.",
        })
    return documents


def get_index():
    global _index
    if _index is None:
        _index = rag_retrieval.CorpusIndex(DATA_DIR, lambda feature: load_documents(feature))
    return _index


def retrieve(query: str, top_k: int = 3, feature: str = "interview") -> dict[str, Any]:
    return get_index().retrieve(query, top_k, feature)


def run_pipeline(query: str, top_k: int = 3, feature: str = "interview") -> dict[str, Any]:
    retrieved = retrieve(query, top_k, feature)
    context = retrieved["results"]
    answer = " ".join(item["text"] for item in context) or "No grounded context was found."
    return {
        "refresh": {**get_index().status()[feature], "status": "validated-active"},
        "retrieve": retrieved,
        "answer": {"text": answer, "sources": [item["source"] for item in context], "method": "diagnostic extraction only; resume model generation is available through /answer"},
        "validate": {"grounded": bool(context), "has_sources": bool(context) and all(item.get("source") for item in context)},
        "review": {"confidence": retrieved["confidence"], "result_count": len(context), "confidence_basis": CONFIDENCE_BASIS},
        "improve": {"recommendation": "Add more relevant reviewed guidance." if not context else "Review source coverage and generated claims against the retrieved evidence."},
    }


def validated_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str) or not payload["query"].strip():
        raise ValueError("query is required.")
    if len(payload["query"]) > 20000:
        raise ValueError("query must not exceed 20000 characters.")
    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        raise ValueError("top_k must be an integer from 1 to 5.")
    feature = payload.get("feature", "interview")
    if feature not in ("interview", "resume"):
        raise ValueError("feature must be interview or resume.")
    return payload["query"].strip(), top_k, feature


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "shared-rag-server", "documents": len(DOCUMENTS) + len(load_documents("resume")),
                    "retrieval_engine": "local-chroma", "embedding_dimensions": 256}), 200


@app.get("/corpus")
def corpus_status():
    return jsonify({"status": "success", "corpora": get_index().status()}), 200


@app.post("/refresh")
def refresh_corpus():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {"feature"}:
        return jsonify({"error": "Refresh accepts only an optional feature (resume or interview)."}), 400
    feature = payload.get("feature")
    if feature is not None and (not isinstance(feature, str) or feature not in ("resume", "interview")):
        return jsonify({"error": "feature must be resume or interview."}), 400
    results = [get_index().refresh(name) for name in ([feature] if feature else ["resume", "interview"])]
    return jsonify({"status": "success", "corpora": results}), 200


@app.errorhandler(rag_retrieval.CorpusError)
def corpus_error(error):
    return jsonify({"error": str(error), "dependency": "rag-corpus", "status": "error"}), 503


@app.post("/retrieve")
def retrieve_route():
    try:
        args = validated_payload()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(retrieve(*args)), 200


@app.post("/pipeline")
def pipeline_route():
    try:
        args = validated_payload()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(run_pipeline(*args)), 200


@app.post("/answer")
def answer_route():
    try:
        query, top_k, feature = validated_payload()
        payload = request.get_json()
        if feature != "resume" or payload.get("task") != "resume-feedback":
            raise ValueError("Supported answer task: resume-feedback with feature resume.")
        allowed = {"task", "feature", "query", "top_k", "candidate_context", "job_description"}
        if set(payload) - allowed:
            raise ValueError("Unsupported answer fields. Model settings and prompts are server-controlled.")
        resume_generation.validate_context(payload)
        result = resume_generation.answer(payload, retrieve(query, top_k, feature))
        return jsonify(result), 200
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except resume_generation.GenerationError as error:
        return jsonify({"error": error.message, "dependency": error.dependency}), error.status_code


if __name__ == "__main__":
    app.run(host=os.getenv("AI_SERVICES_HOST", "127.0.0.1"), port=PORT)
