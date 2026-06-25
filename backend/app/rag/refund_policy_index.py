from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from app.db.database import get_connection, initialize_schema
from app.rag.policy_index import _embedding, chunk_policy, load_policy

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SUPPLEMENT_PATH = DATA_DIR / "refund_policy_supplement.md"
CHROMA_PATH = DATA_DIR / "chroma_refund_policy"
COLLECTION_NAME = "shopward_refund_policy"


def load_refund_policy_corpus() -> str:
    supplement = SUPPLEMENT_PATH.read_text(encoding="utf-8") if SUPPLEMENT_PATH.exists() else ""
    return f"{load_policy()}\n\n{supplement}".strip()


def _policy_hash(policy_text: str) -> str:
    return hashlib.sha256(policy_text.encode("utf-8")).hexdigest()


def _get_chroma_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def rebuild_refund_policy_index() -> None:
    initialize_schema()
    corpus = load_refund_policy_corpus()
    chunks = chunk_policy(corpus)
    collection = _get_chroma_collection()

    existing = collection.get(include=[])
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    if not chunks:
        return

    ids = [f"refund_{index:03d}" for index in range(1, len(chunks) + 1)]
    documents = [f"{chunk['section_title']}\n{chunk['content']}" for chunk in chunks]
    embeddings = [_embedding(document) for document in documents]
    metadatas = [
        {
            "source": "refund_policy",
            "section_title": chunk["section_title"],
            "chunk_id": chunk_id,
        }
        for chunk, chunk_id in zip(chunks, ids)
    ]
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    now = datetime.utcnow().isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO PolicyIndexMetadata (key, value, updated_at)
            VALUES ('refund_policy_chroma_hash', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (_policy_hash(corpus), now),
        )


def ensure_refund_policy_index() -> None:
    initialize_schema()
    corpus = load_refund_policy_corpus()
    current_hash = _policy_hash(corpus)
    with get_connection() as connection:
        hash_row = connection.execute(
            "SELECT value FROM PolicyIndexMetadata WHERE key = 'refund_policy_chroma_hash'"
        ).fetchone()
    collection = _get_chroma_collection()
    if collection.count() == 0 or not hash_row or hash_row["value"] != current_hash:
        rebuild_refund_policy_index()


def retrieve_refund_policy_sections(query: str, limit: int = 5) -> list[dict]:
    ensure_refund_policy_index()
    collection = _get_chroma_collection()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[_embedding(query)],
        n_results=min(limit, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    sections: list[dict] = []
    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    distances = results.get("distances") or [[]]

    for document, metadata, distance in zip(documents[0], metadatas[0], distances[0]):
        section_title = str(metadata.get("section_title", "Refund Policy"))
        content = str(document)
        if content.startswith(section_title):
            content = content[len(section_title) :].lstrip("\n")
        score = max(0.0, 1.0 - float(distance))
        sections.append(
            {
                "chunk_id": metadata.get("chunk_id"),
                "section_title": section_title,
                "content": content,
                "score": round(score, 4),
            }
        )
    return sections
