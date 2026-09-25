from __future__ import annotations

import os
import re
from typing import Any

from flask import Flask, jsonify, request

app = Flask(__name__)
PORT = int(os.getenv("RAG_PORT", "8766"))

DOCUMENTS = [
    {
        "id": "interview-star",
        "title": "STAR interview responses",
        "text": "Strong behavioural answers explain the situation, task, action, and measurable result.",
        "source": "shared://interview/star-method",
    },
    {
        "id": "api-design",
        "title": "API design fundamentals",
        "text": "Good API answers discuss validation, error handling, observability, security, and performance trade-offs.",
        "source": "shared://interview/api-design",
    },
    {
        "id": "technical-communication",
        "title": "Technical communication",
        "text": "Clear interview answers state assumptions, compare alternatives, and justify a decision with evidence.",
        "source": "shared://interview/communication",
    },
]


def retrieve(query: str, top_k: int = 3) -> dict[str, Any]:
    terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    scored = []
    for document in DOCUMENTS:
        haystack = f"{document['title']} {document['text']}".lower()
        score = sum(term in haystack for term in terms)
        scored.append((score, document))
    matches = [document for score, document in sorted(scored, key=lambda item: item[0], reverse=True)[:max(1, min(top_k, 5))] if score > 0]
    confidence = "high" if len(matches) >= 2 else "medium" if matches else "low"
    return {
        "query": query,
        "results": [{"title": item["title"], "text": item["text"], "source": item["source"], "score": 1} for item in matches],
        "confidence": confidence,
    }


def run_pipeline(query: str, top_k: int = 3) -> dict[str, Any]:
    refreshed = {"document_count": len(DOCUMENTS), "status": "refreshed"}
    retrieved = retrieve(query, top_k)
    context = retrieved["results"]
    answer = " ".join(item["text"] for item in context) or "No grounded context was found."
    validation = {"grounded": bool(context), "has_sources": all(item.get("source") for item in context)}
    review = {"confidence": retrieved["confidence"], "result_count": len(context)}
    improvement = "Add more indexed interview guidance." if not context else "Grounding sources are available."
    return {
        "refresh": refreshed,
        "retrieve": retrieved,
        "answer": {"text": answer, "sources": [item["source"] for item in context]},
        "validate": validation,
        "review": review,
        "improve": {"recommendation": improvement},
    }


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "service": "shared-rag-server", "documents": len(DOCUMENTS)}), 200


@app.post("/retrieve")
def retrieve_route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str) or not payload["query"].strip():
        return jsonify({"error": "query is required."}), 400
    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        return jsonify({"error": "top_k must be a positive integer."}), 400
    return jsonify(retrieve(payload["query"].strip(), top_k)), 200


@app.post("/pipeline")
def pipeline_route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str) or not payload["query"].strip():
        return jsonify({"error": "query is required."}), 400
    return jsonify(run_pipeline(payload["query"].strip(), payload.get("top_k", 3))), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT)
