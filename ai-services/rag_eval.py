"""Measure real local vector retrieval; degraded fallback never counts as vector success."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

SERVICE_DIR = Path(__file__).resolve().parent


def metrics(results: list[dict], expected: set[str]) -> dict:
    actual = [item["chunk_id"] for item in results[:5]]
    relevant = sorted(set(actual) & expected)
    return {"retrieved_chunk_ids": actual, "relevant_chunk_ids": relevant,
            "precision_at_5": len(relevant) / 5,
            "recall_at_5": len(relevant) / len(expected) if expected else None}


def evaluate(index, benchmarks: list[dict]) -> dict:
    refreshes = [index.refresh(feature) for feature in sorted({case["feature"] for case in benchmarks})]
    cases = []
    for case in benchmarks:
        expected = set(case["expected_relevant_chunks"])
        result = index.retrieve(case["query"], 5, case["feature"])
        _, chunks = index._active(case["feature"])
        if not expected.issubset({chunk["chunk_id"] for chunk in chunks}):
            raise ValueError(f"Benchmark {case['name']} expects a chunk absent from the approved corpus.")
        vector = metrics(result["results"], expected)
        baseline = metrics(index.lexical_results(case["query"], chunks, 5), expected)
        cases.append({**case, "retrieval_mode": result["retrieval_mode"], "vector_store_status": result["vector_store_status"],
            "confidence": result["confidence"], "corpus_version": result["corpus_version"],
            "vector": vector, "lexical_baseline": baseline,
            "passed": result["retrieval_mode"] == "vector" and (
                vector["recall_at_5"] == 1 if expected else not result["results"])})
    positives = [case for case in cases if case["expected_relevant_chunks"]]
    negatives = [case for case in cases if not case["expected_relevant_chunks"]]
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "status": "pass" if all(c["passed"] for c in cases) else "fail",
        "scope": "Retrieval only: actual local Chroma, no LLM calls. Expected relevant chunks are manually specified, not inferred from returned ranks.",
        "metric_definition": "P@5 = relevant chunks / 5 even when fewer than 5 are returned; R@5 = relevant retrieved / expected relevant. Negative-query recall is undefined and excluded from means.",
        "refreshes": refreshes, "cases": cases,
        "summary": {"positive_queries": len(positives), "negative_queries": len(negatives),
            "mean_precision_at_5": sum(c["vector"]["precision_at_5"] for c in positives) / len(positives),
            "mean_recall_at_5": sum(c["vector"]["recall_at_5"] for c in positives) / len(positives),
            "negative_queries_without_context": sum(not c["vector"]["retrieved_chunk_ids"] for c in negatives),
            "all_queries_used_vector": all(c["retrieval_mode"] == "vector" for c in cases)},
        "limitations": ["Small authored corpus and nine fixed cases; not a general semantic-search benchmark.",
                        "Hash embeddings are deterministic token features, not a trained semantic model.",
                        "Successful retrieval does not establish factual correctness of generated answers."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Isolated local Chroma/corpus directory.")
    parser.add_argument("--output", type=Path, help="Save complete retrieval evidence as JSON.")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("rag_evaluation_server", SERVICE_DIR / "rag_server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    if args.data_dir:
        server.DATA_DIR = args.data_dir
    result = evaluate(server.get_index(), json.loads((SERVICE_DIR / "retrieval_benchmarks.json").read_text()))
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
