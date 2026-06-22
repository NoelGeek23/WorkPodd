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
    return Path(configured) if configured else DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_schema() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


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
