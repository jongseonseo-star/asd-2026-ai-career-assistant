"""Local Lab 8 retrieval: approved corpus -> chunks -> 256-D vectors -> Chroma.

No embedding download or external service is used. Refresh builds and validates a
new collection before atomically activating it. Failed refreshes retain the old
index; changed sources must be refreshed before they can support generation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from threading import RLock
import time
from typing import Callable
from uuid import uuid4

import chromadb
from chromadb.config import Settings

EMBEDDING_DIMENSIONS = 256
EMBEDDING_VERSION = "sha256-signed-token-hash-256-v1"
MAX_CHUNK_WORDS = 80
MIN_SIMILARITY = 0.08
FEATURES = {"resume", "interview", "jobs"}
STOP_WORDS = frozenset("""
a an and are as at be been being but by can could did do does for from
had has have how i if in into is it its me more most my not of on or our
should so some than that the their them then there these they this those
to too us was we were what when where which who why will with would you your
about also any please tell explain describe show give provide recommend
""".split())
CONFIDENCE_BASIS = (
    "Evidence coverage and authority: high requires at least two distinct tier_1/tier_2 sources; "
    "medium means some relevant evidence, including project-authored tier_3 guidance; low means none. "
    "Degraded retrieval is never high. This is not a probability of factual correctness."
)


class CorpusError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word
            for word in words if len(word) > 2 and word not in STOP_WORDS]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Repeatable signed feature hashing, not a trained semantic embedding."""
    vectors = []
    for text in texts:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token, count in Counter(tokens(text)).items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            position = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMENSIONS
            vector[position] += (1 if digest[2] & 1 else -1) * (1 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        vectors.append([value / norm for value in vector] if norm else vector)
    return vectors


def chunk_text(text: str) -> list[str]:
    """Keep contiguous source excerpts, preferring sentence boundaries <=80 words."""
    words = list(re.finditer(r"\S+", text))
    chunks, start = [], 0
    while start < len(words):
        end = min(start + MAX_CHUNK_WORDS, len(words))
        if end < len(words):
            boundaries = [i + 1 for i in range(start + 29, end) if words[i].group().endswith((".", "!", "?"))]
            if boundaries:
                end = boundaries[-1]
        chunks.append(text[words[start].start():words[end - 1].end()])
        start = end
    return chunks


def source_version(documents: list[dict]) -> str:
    body = {"embedding": EMBEDDING_VERSION, "chunk_words": MAX_CHUNK_WORDS,
            "documents": documents}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_query(query: str, top_k: int, feature: str) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > 20000:
        raise ValueError("query must contain 1 to 20000 characters.")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        raise ValueError("top_k must be an integer from 1 to 5.")
    if not isinstance(feature, str) or feature not in FEATURES:
        raise ValueError("feature must be resume, interview or jobs.")


class CorpusIndex:
    def __init__(self, directory: Path, document_loader: Callable[[str], list[dict]]):
        self.directory = Path(directory)
        self.document_loader = document_loader
        self.lock = RLock()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.directory / "chroma"),
                settings=Settings(anonymized_telemetry=False))
        return self._client

    def _state(self) -> dict:
        path = self.directory / "active.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CorpusError("The active corpus manifest is unreadable; refresh is required.") from error

    def _audit(self, operation: str, details: dict, started: float) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"request_id": str(uuid4()), "timestamp": now(), "operation": operation,
                  "duration_ms": round((time.monotonic() - started) * 1000), **details}
        with (self.directory / "rag-audit.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _chunks(self, feature: str, documents: list[dict], version: str, indexed_at: str) -> list[dict]:
        chunks = []
        seen_sources = set()
        for document in documents:
            if any(not isinstance(document.get(key), str) or not document[key].strip()
                   for key in ("id", "title", "text", "source")):
                raise CorpusError("An approved document is missing its identity, text or source.")
            if document["source"] in seen_sources:
                raise CorpusError("Approved source identifiers must be unique.")
            seen_sources.add(document["source"])
            tier = document.get("authority_tier", "tier_3")
            if tier not in {"tier_1", "tier_2", "tier_3"}:
                raise CorpusError("A source has an unsupported authority tier.")
            for number, text in enumerate(chunk_text(document["text"]), 1):
                chunks.append({"id": document["id"] if number == 1 else f"{document['id']}-{number}",
                    "chunk_id": f"{feature}:{document['id']}:{number}", "document_id": document["id"],
                    "source_id": document["source"], "source": f"{document['source']}#chunk-{number}",
                    "title": document["title"], "text": text, "feature": feature, "authority_tier": tier,
                    "provenance": document.get("provenance", "Project-authored guidance."),
                    "source_version": hashlib.sha256(document["text"].encode()).hexdigest(),
                    "corpus_version": version, "indexed_at": indexed_at, "chunk_number": number})
        if not chunks:
            raise CorpusError("No approved non-empty documents are available for indexing.")
        return chunks

    def refresh(self, feature: str = "resume") -> dict:
        if not isinstance(feature, str) or feature not in FEATURES:
            raise ValueError("feature must be resume, interview or jobs.")
        started = time.monotonic()
        with self.lock:
            collection_name = f"career-{feature}-{uuid4().hex}"
            try:
                documents = self.document_loader(feature)
                version, indexed_at = source_version(documents), now()
                chunks = self._chunks(feature, documents, version, indexed_at)
                collection = self.client.create_collection(collection_name, embedding_function=None,
                    metadata={"hnsw:space": "cosine", "embedding_version": EMBEDDING_VERSION})
                vectors = embed_texts([chunk["title"] + " " + chunk["text"] for chunk in chunks])
                collection.add(ids=[chunk["chunk_id"] for chunk in chunks],
                    documents=[chunk["text"] for chunk in chunks], embeddings=vectors,
                    metadatas=[{key: value for key, value in chunk.items() if key != "text"} for chunk in chunks])
                # Check stored content and a real query before exposing the new index.
                stored = collection.get(include=["documents", "metadatas"])
                if collection.count() != len(chunks) or set(stored["ids"]) != {c["chunk_id"] for c in chunks}:
                    raise CorpusError("Staged index did not preserve every chunk.")
                stored_by_id = dict(zip(stored["ids"], stored["documents"]))
                if any(stored_by_id[c["chunk_id"]] != c["text"] for c in chunks):
                    raise CorpusError("Staged index content validation failed.")
                probe = collection.query(query_embeddings=[vectors[0]], n_results=1)
                if not probe["ids"][0] or probe["distances"][0][0] > 0.001:
                    raise CorpusError("Staged vector retrieval validation failed.")
                if source_version(self.document_loader(feature)) != version:
                    raise CorpusError("Approved sources changed during refresh; retry with a stable corpus.")
                corpus_dir = self.directory / "corpus"
                corpus_dir.mkdir(parents=True, exist_ok=True)
                corpus_file = corpus_dir / f"{collection_name}.jsonl"
                corpus_text = "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks)
                corpus_file.write_text(corpus_text, encoding="utf-8")
                previous = self._state()
                record = {"feature": feature, "collection": collection_name, "corpus_version": version,
                    "embedding_version": EMBEDDING_VERSION, "embedding_dimensions": EMBEDDING_DIMENSIONS,
                    "indexed_at": indexed_at, "document_count": len(documents), "chunk_count": len(chunks),
                    "corpus_file": str(corpus_file.relative_to(self.directory)),
                    "corpus_sha256": hashlib.sha256(corpus_text.encode()).hexdigest(),
                    "previous_collection": previous.get(feature, {}).get("collection")}
                staged_manifest = self.directory / f"active-{uuid4().hex}.tmp"
                staged_manifest.write_text(json.dumps({**previous, feature: record}, indent=2), encoding="utf-8")
                staged_manifest.replace(self.directory / "active.json")
                result = {"status": "success", "vector_store_status": "ready", **record}
                self._audit("refresh_corpus", result, started)
                return result
            except Exception as error:
                # Only remove the new unactivated collection; never destroy the active index.
                try:
                    if self._state().get(feature, {}).get("collection") != collection_name:
                        self.client.delete_collection(collection_name)
                except Exception:
                    pass
                self._audit("refresh_corpus", {"status": "error", "feature": feature, "error": str(error)}, started)
                raise CorpusError(f"Corpus refresh failed; previous active index retained: {error}") from error

    def status(self) -> dict:
        with self.lock:
            states = self._state()
            return {feature: {**record, "stale": source_version(self.document_loader(feature)) != record["corpus_version"]}
                    for feature, record in states.items()}

    def _active(self, feature: str) -> tuple[dict, list[dict]]:
        state = self._state().get(feature)
        if state is None:
            self.refresh(feature)
            state = self._state()[feature]
        if state["embedding_version"] != EMBEDDING_VERSION or source_version(self.document_loader(feature)) != state["corpus_version"]:
            raise CorpusError("Approved sources or embedding logic changed. Run POST /refresh before using this corpus.")
        corpus_text = (self.directory / state["corpus_file"]).read_text(encoding="utf-8")
        if hashlib.sha256(corpus_text.encode()).hexdigest() != state["corpus_sha256"]:
            raise CorpusError("Stored corpus checksum does not match its validated version. Refresh is required.")
        return state, [json.loads(line) for line in corpus_text.splitlines()]

    @staticmethod
    def lexical_results(query: str, chunks: list[dict], top_k: int) -> list[dict]:
        terms = set(tokens(query))
        ranked = []
        for chunk in chunks:
            overlap = len(terms & set(tokens(chunk["title"] + " " + chunk["text"])))
            if overlap:
                ranked.append({**chunk, "score": overlap, "distance": None, "token_overlap": overlap})
        ranked.sort(key=lambda item: (item["authority_tier"], -item["score"], item["chunk_id"]))
        return [{**item, "rank": rank} for rank, item in enumerate(ranked[:top_k], 1)]

    def retrieve(self, query: str, top_k: int = 3, feature: str = "interview") -> dict:
        validate_query(query, top_k, feature)
        started = time.monotonic()
        with self.lock:
            state, chunks = self._active(feature)
            terms = set(tokens(query))
            mode, vector_error = "vector", None
            try:
                collection = self.client.get_collection(state["collection"], embedding_function=None)
                # The approved corpus is small. Ask Chroma for candidate vectors,
                # then reject unrelated matches before returning up to top_k.
                response = collection.query(query_embeddings=embed_texts([query]), n_results=len(chunks),
                    include=["documents", "metadatas", "distances"])
                ranked = []
                for identifier, text, metadata, distance in zip(response["ids"][0], response["documents"][0],
                        response["metadatas"][0], response["distances"][0]):
                    overlap = len(terms & set(tokens(metadata["title"] + " " + text)))
                    similarity = 1 - distance
                    if overlap and similarity >= MIN_SIMILARITY:
                        ranked.append({**metadata, "chunk_id": identifier, "text": text,
                                       "distance": distance, "score": similarity, "token_overlap": overlap})
                ranked.sort(key=lambda item: (item["authority_tier"], item["distance"], item["chunk_id"]))
                results = [{**item, "rank": rank} for rank, item in enumerate(ranked[:top_k], 1)]
            except Exception as error:
                mode, vector_error = "lexical_fallback", f"{type(error).__name__}: {error}"
                results = self.lexical_results(query, chunks, top_k)
            authoritative = {item["source_id"] for item in results if item["authority_tier"] in {"tier_1", "tier_2"}}
            confidence = "high" if len(authoritative) >= 2 and mode == "vector" else "medium" if results else "low"
            result = {"query": query, "feature": feature, "results": results, "confidence": confidence,
                "confidence_basis": CONFIDENCE_BASIS, "retrieval_mode": mode,
                "vector_store_status": "ready" if mode == "vector" else "degraded",
                "corpus_version": state["corpus_version"], "indexed_at": state["indexed_at"],
                "embedding_version": EMBEDDING_VERSION, "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "retrieval_summary": {"k": top_k, "retrieved_count": len(results),
                                      "top_chunk": results[0]["chunk_id"] if results else None}}
            if vector_error:
                result["vector_store_error"] = vector_error
                result["warning"] = "Vector retrieval failed; explicitly degraded lexical fallback is in use."
            self._audit("retrieve_context", {"query": query, "feature": feature, "retrieval_mode": mode,
                "corpus_version": state["corpus_version"], "chunk_ids": [x["chunk_id"] for x in results],
                "confidence": confidence, "vector_store_error": vector_error}, started)
            return result
