"""SQLite storage for observations, baselines, and events. Never stores raw images."""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from .config import Config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    local_features TEXT NOT NULL,
    deep_result TEXT,
    deep_analysis BOOLEAN DEFAULT FALSE,
    git_activity TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,          -- 'deviation', 'intervention', 'flag'
    severity TEXT NOT NULL DEFAULT 'info',  -- 'info', 'warning', 'critical'
    marker TEXT,                       -- which marker triggered this
    value TEXT,                        -- observed value
    baseline TEXT,                     -- expected value
    message TEXT NOT NULL,
    notified BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS baselines (
    marker TEXT PRIMARY KEY,
    mean REAL NOT NULL,
    std REAL NOT NULL,
    n INTEGER NOT NULL,
    last_updated TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obs_captured_at ON observations(captured_at);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_notified ON events(notified);
"""


def get_db(config: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_observation(
    conn: sqlite3.Connection,
    captured_at: datetime,
    local_features: dict,
    deep_result: dict | None = None,
    git_activity: dict | None = None,
):
    conn.execute(
        "INSERT INTO observations (captured_at, local_features, deep_result, deep_analysis, git_activity) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            captured_at.isoformat(),
            json.dumps(local_features),
            json.dumps(deep_result) if deep_result else None,
            deep_result is not None,
            json.dumps(git_activity) if git_activity else None,
        ),
    )
    conn.commit()


def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    message: str,
    severity: str = "info",
    marker: str | None = None,
    value: str | None = None,
    baseline: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (event_type, severity, marker, value, baseline, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (event_type, severity, marker, value, baseline, message),
    )
    conn.commit()
    return cur.lastrowid


def recent_observations(conn: sqlite3.Connection, limit: int = 100):
    return conn.execute(
        "SELECT * FROM observations ORDER BY captured_at DESC LIMIT ?", (limit,)
    ).fetchall()


def observations_since(conn: sqlite3.Connection, since: datetime):
    return conn.execute(
        "SELECT * FROM observations WHERE captured_at >= ? ORDER BY captured_at ASC",
        (since.isoformat(),),
    ).fetchall()


def observation_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) as c FROM observations").fetchone()["c"]


def deep_observation_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) as c FROM observations WHERE deep_analysis = TRUE"
    ).fetchone()["c"]


def last_notification_time(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT created_at FROM events WHERE notified = TRUE ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        return datetime.fromisoformat(row["created_at"])
    return None


def update_baseline(conn: sqlite3.Connection, marker: str, mean: float, std: float, n: int):
    conn.execute(
        "INSERT OR REPLACE INTO baselines (marker, mean, std, n, last_updated) "
        "VALUES (?, ?, ?, ?, ?)",
        (marker, mean, std, n, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_baseline(conn: sqlite3.Connection, marker: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM baselines WHERE marker = ?", (marker,)
    ).fetchone()
    return dict(row) if row else None


def all_baselines(conn: sqlite3.Connection):
    return {r["marker"]: dict(r) for r in conn.execute("SELECT * FROM baselines").fetchall()}
