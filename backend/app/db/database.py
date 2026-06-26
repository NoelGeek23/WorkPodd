from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "refund_agent.sqlite"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_db_path() -> Path:
    configured = os.getenv("SQLITE_DB_PATH")
    if not configured:
        return DEFAULT_DB_PATH
    path = Path(configured)
    if path.is_absolute():
        return path
    return (APP_DIR / path).resolve()


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _migrate_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(ReturnRequest)").fetchall()
    }
    if "admin_message" not in columns:
        connection.execute("ALTER TABLE ReturnRequest ADD COLUMN admin_message TEXT")

    evidence_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(Evidence)").fetchall()
    }
    if "content_type" not in evidence_columns:
        connection.execute("ALTER TABLE Evidence ADD COLUMN content_type TEXT")

    connection.execute(
        """
        UPDATE Orders
        SET status = 'returned'
        WHERE order_id IN (
            SELECT order_id FROM ReturnRequest WHERE status = 'Approved'
        )
          AND status != 'returned'
        """
    )


def initialize_schema() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_schema(connection)


def table_count(table_name: str) -> int:
    with get_connection() as connection:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"])


def has_seed_data() -> bool:
    initialize_schema()
    required_tables = ("Customer", "Product", "Orders", "ReturnRequest", "RefundHistory")
    return all(table_count(table) > 0 for table in required_tables)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def bool_to_int(value: bool) -> int:
    return 1 if value else 0


def int_to_bool(value: int | bool | None) -> bool:
    return bool(value)
