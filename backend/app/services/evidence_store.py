from __future__ import annotations

import base64
import mimetypes
from datetime import date
from pathlib import Path
from uuid import uuid4

EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "evidence"


def ensure_evidence_dir() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _extension_for(content_type: str, file_name: str) -> str:
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
    if guessed:
        return guessed
    suffix = Path(file_name).suffix
    return suffix if suffix else ".bin"


def save_evidence_file(
    evidence_id: str,
    file_name: str,
    content_type: str,
    data_base64: str,
) -> None:
    ensure_evidence_dir()
    payload = data_base64.strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    raw = base64.b64decode(payload)
    extension = _extension_for(content_type, file_name)
    target = EVIDENCE_DIR / f"{evidence_id}{extension}"
    target.write_bytes(raw)


def get_evidence_file(evidence_id: str) -> tuple[Path, str] | None:
    ensure_evidence_dir()
    matches = list(EVIDENCE_DIR.glob(f"{evidence_id}.*"))
    if not matches:
        return None
    path = matches[0]
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path, content_type


def persist_ticket_evidence(connection, request_id: str, files: list) -> None:
    connection.execute("DELETE FROM Evidence WHERE request_id = ?", (request_id,))
    if not files:
        return

    rows = []
    for file in files:
        evidence_id = f"ev_{uuid4().hex[:8]}"
        file_name = getattr(file, "file_name", None) or file.get("file_name")
        content_type = getattr(file, "content_type", None) or file.get("content_type") or "application/octet-stream"
        data_base64 = getattr(file, "data_base64", None) or file.get("data_base64")
        if data_base64:
            save_evidence_file(evidence_id, file_name, content_type, data_base64)
        rows.append(
            (
                evidence_id,
                request_id,
                "photo",
                file_name,
                content_type,
                0,
                date.today().isoformat(),
            )
        )

    connection.executemany(
        """
        INSERT INTO Evidence (
            evidence_id, request_id, type, file_path, content_type, verified, uploaded_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
