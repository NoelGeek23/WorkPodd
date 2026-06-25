from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from app.db.database import get_connection, initialize_schema

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POLICY_PATH = DATA_DIR / "refund_policy.md"
VECTOR_SIZE = 128
TOKEN_RE = re.compile(r"[a-z0-9]+")


def load_policy() -> str:
    return POLICY_PATH.read_text(encoding="utf-8")


def _policy_hash(policy_text: str) -> str:
    return hashlib.sha256(policy_text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _embedding(text: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % VECTOR_SIZE
        vector[index] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def chunk_policy(policy_text: str) -> list[dict]:
    chunks: list[dict] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for line in policy_text.splitlines():
        if line.startswith("## "):
            if current_lines:
                content = "\n".join(current_lines).strip()
                chunks.append({"section_title": current_title, "content": content})
            current_title = line.removeprefix("## ").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append({"section_title": current_title, "content": "\n".join(current_lines).strip()})

    return [chunk for chunk in chunks if chunk["content"]]


def rebuild_policy_index() -> None:
    initialize_schema()
    policy_text = load_policy()
    chunks = chunk_policy(policy_text)
    now = datetime.utcnow().isoformat()

    with get_connection() as connection:
        connection.execute("DELETE FROM PolicyChunk")
        connection.execute("DELETE FROM PolicyIndexMetadata")
        connection.executemany(
            """
            INSERT INTO PolicyChunk (
                chunk_id, section_title, content, embedding_json, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    f"policy_{index:03d}",
                    chunk["section_title"],
                    chunk["content"],
                    json.dumps(_embedding(f"{chunk['section_title']}\n{chunk['content']}")),
                    now,
                )
                for index, chunk in enumerate(chunks, start=1)
            ],
        )
        connection.execute(
            """
            INSERT INTO PolicyIndexMetadata (key, value, updated_at)
            VALUES ('policy_hash', ?, ?)
            """,
            (_policy_hash(policy_text), now),
        )


def ensure_policy_index() -> None:
    initialize_schema()
    current_hash = _policy_hash(load_policy())
    with get_connection() as connection:
        count_row = connection.execute("SELECT COUNT(*) AS count FROM PolicyChunk").fetchone()
        hash_row = connection.execute(
            "SELECT value FROM PolicyIndexMetadata WHERE key = 'policy_hash'"
        ).fetchone()
    if int(count_row["count"]) == 0 or not hash_row or hash_row["value"] != current_hash:
        rebuild_policy_index()


def retrieve_policy_sections(query: str, limit: int = 4) -> list[dict]:
    ensure_policy_index()
    query_vector = _embedding(query)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT chunk_id, section_title, content, embedding_json FROM PolicyChunk"
        ).fetchall()

    ranked = []
    for row in rows:
        chunk_vector = json.loads(row["embedding_json"])
        score = _cosine(query_vector, chunk_vector)
        ranked.append(
            {
                "chunk_id": row["chunk_id"],
                "section_title": row["section_title"],
                "content": row["content"],
                "score": round(score, 4),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


POLICY_QUERY_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "how",
    "when",
    "where",
    "which",
    "who",
    "why",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "my",
    "your",
    "our",
    "their",
    "i",
    "we",
    "you",
    "me",
    "about",
    "for",
    "of",
    "in",
    "on",
    "at",
    "to",
    "from",
    "shopward",
    "policy",
    "policies",
    "rule",
    "rules",
    "say",
    "says",
    "tell",
    "know",
    "want",
    "need",
    "please",
    "that",
    "this",
    "there",
    "have",
    "has",
    "get",
    "give",
}

POLICY_QUERY_PREFIXES = (
    "what is the ",
    "what is our ",
    "what is ",
    "what are the ",
    "what are ",
    "tell me about the ",
    "tell me about ",
    "explain the ",
    "explain ",
    "can you tell me about ",
    "do we have a ",
    "do we have ",
)


def extract_policy_focus_terms(query: str) -> list[str]:
    tokens = TOKEN_RE.findall(query.lower())
    seen: set[str] = set()
    focus: list[str] = []
    for token in tokens:
        if token in POLICY_QUERY_STOP_WORDS or len(token) <= 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        focus.append(token)
    return focus


def format_policy_topic(query: str) -> str:
    text = query.strip().rstrip("?.!").lower()
    for prefix in POLICY_QUERY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text or query.strip().rstrip("?.!")


def _policy_corpus_text() -> str:
    return load_policy().lower()


def _section_text(section: dict) -> str:
    return f"{section.get('section_title', '')}\n{section.get('content', '')}".lower()


def validate_policy_answer(query: str, sections: list[dict]) -> dict[str, str | None]:
    if not sections:
        return {"verdict": "unsure", "topic": None, "reason": "no_sections"}

    focus_terms = extract_policy_focus_terms(query)
    if not focus_terms:
        primary_score = float(sections[0].get("score", 0))
        if primary_score < 0.12:
            return {"verdict": "unsure", "topic": None, "reason": "low_score_no_focus_terms"}
        return {"verdict": "answer", "topic": None, "reason": "generic_policy_query"}

    corpus = _policy_corpus_text()
    missing_from_policy = [term for term in focus_terms if term not in corpus]
    if missing_from_policy:
        return {
            "verdict": "not_found",
            "topic": format_policy_topic(query),
            "reason": f"terms_missing_from_policy:{','.join(missing_from_policy)}",
        }

    primary = sections[0]
    primary_score = float(primary.get("score", 0))
    section_text = _section_text(primary)
    title = str(primary.get("section_title", "")).lower()
    matched_terms = [term for term in focus_terms if term in section_text]
    coverage = len(matched_terms) / len(focus_terms)

    if primary_score < 0.10:
        return {"verdict": "unsure", "topic": None, "reason": "low_rag_score"}

    if coverage < 0.5:
        return {"verdict": "unsure", "topic": None, "reason": "low_term_coverage"}

    if coverage < 1.0:
        uncovered = [term for term in focus_terms if term not in section_text]
        if uncovered:
            return {"verdict": "unsure", "topic": None, "reason": f"partial_match:{','.join(uncovered)}"}

    if len(focus_terms) >= 2 and primary_score < 0.16:
        title_hits = sum(1 for term in focus_terms if term in title)
        if title_hits == 0:
            return {"verdict": "unsure", "topic": None, "reason": "weak_title_match"}

    return {"verdict": "answer", "topic": None, "reason": "validated"}
