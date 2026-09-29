from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .inspectors import classify_ai_mention


SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workshop_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    classification TEXT NOT NULL,
    tools TEXT NOT NULL DEFAULT '',
    evidence_snippet TEXT NOT NULL,
    source_title TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(review_status IN ('pending','confirmed','rejected','unclear')),
    reviewer_note TEXT,
    reviewed_at TEXT,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workshop_id, evidence_type, classification, evidence_snippet)
);

CREATE INDEX IF NOT EXISTS idx_provenance_review_status
ON provenance_candidates(review_status);

CREATE INDEX IF NOT EXISTS idx_provenance_workshop_id
ON provenance_candidates(workshop_id);

CREATE INDEX IF NOT EXISTS idx_provenance_evidence_type
ON provenance_candidates(evidence_type);
"""

@dataclass(frozen=True)
class Candidate:
    workshop_id: str
    evidence_type: str
    classification: str
    tools: str
    evidence_snippet: str
    source_title: str | None
    created_at: int | None
    updated_at: int | None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _insert_or_refresh(
    conn: sqlite3.Connection,
    candidate: Candidate,
) -> bool:
    existed = conn.execute(
        """
        SELECT 1 FROM provenance_candidates
        WHERE workshop_id = ?
          AND evidence_type = ?
          AND classification = ?
          AND evidence_snippet = ?
        """,
        (
            candidate.workshop_id,
            candidate.evidence_type,
            candidate.classification,
            candidate.evidence_snippet,
        ),
    ).fetchone() is not None

    conn.execute(
        """
        INSERT INTO provenance_candidates(
            workshop_id, evidence_type, classification, tools,
            evidence_snippet, source_title, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(workshop_id, evidence_type, classification, evidence_snippet)
        DO UPDATE SET
            tools = excluded.tools,
            source_title = excluded.source_title,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE provenance_candidates.review_status = 'pending'
        """,
        (
            candidate.workshop_id,
            candidate.evidence_type,
            candidate.classification,
            candidate.tools,
            candidate.evidence_snippet,
            candidate.source_title,
            candidate.created_at,
            candidate.updated_at,
        ),
    )
    return not existed


def _extract_candidates(conn: sqlite3.Connection) -> tuple[int, int]:
    inserted = 0
    refreshed = 0

    rows = conn.execute(
        """
        SELECT workshop_id, title, description, time_created, time_updated
        FROM mods
        WHERE trim(COALESCE(title, '') || COALESCE(description, '')) != ''
        """
    )

    for row in rows:
        title = row["title"]
        description = row["description"]
        result = classify_ai_mention(title, description)
        if not result or not result.get("evidence_type"):
            continue

        evidence_type = result["evidence_type"]
        classification = result["provenance_classification"]
        snippet = result["snippet"]
        candidate = Candidate(
            workshop_id=str(row["workshop_id"]),
            evidence_type=evidence_type,
            classification=classification,
            tools=",".join(result["tools"]),
            evidence_snippet=snippet,
            source_title=title,
            created_at=row["time_created"],
            updated_at=row["time_updated"],
        )

        if _insert_or_refresh(conn, candidate):
            inserted += 1
        else:
            refreshed += 1

    return inserted, refreshed


def extract_candidates(conn: sqlite3.Connection) -> tuple[int, int]:
    ensure_schema(conn)
    with conn:
        return _extract_candidates(conn)


def _refresh_pending(conn: sqlite3.Connection, *, all_types: bool) -> tuple[int, int, int]:
    ensure_schema(conn)
    with conn:
        # Acquire the write lock before changing derived review aids or candidates.
        conn.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "provenance_group_members" in tables:
            conn.execute("DELETE FROM provenance_group_members")
        if "provenance_groups" in tables:
            conn.execute("DELETE FROM provenance_groups")
        condition = "" if all_types else " AND evidence_type IN ('code', 'development_general')"
        removed = conn.execute(
            "DELETE FROM provenance_candidates WHERE review_status = 'pending'" + condition
        ).rowcount
        inserted, refreshed = _extract_candidates(conn)
    return removed, inserted, refreshed


def refresh_all_pending_candidates(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Atomically rebuild all pending evidence; reviewed rows remain unchanged.

    Returns (removed pending, inserted, existing matches). Existing matches
    include reviewed evidence, which is preserved rather than updated.
    Group caches are invalidated; rebuild them before further grouped review.
    """
    return _refresh_pending(conn, all_types=True)


def refresh_pending_development_candidates(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Compatibility workflow: replace pending code/development evidence only."""
    return _refresh_pending(conn, all_types=False)


def next_pending(conn: sqlite3.Connection, evidence_type: str | None = None):
    ensure_schema(conn)

    if evidence_type:
        return conn.execute(
            """
            SELECT * FROM provenance_candidates
            WHERE review_status = 'pending' AND evidence_type = ?
            ORDER BY updated_at DESC, id ASC
            LIMIT 1
            """,
            (evidence_type,),
        ).fetchone()

    return conn.execute(
        """
        SELECT * FROM provenance_candidates
        WHERE review_status = 'pending'
        ORDER BY
            CASE evidence_type
                WHEN 'code' THEN 0
                WHEN 'development_general' THEN 1
                WHEN 'translation' THEN 2
                WHEN 'assets' THEN 3
                WHEN 'audio' THEN 4
                ELSE 5
            END,
            updated_at DESC,
            id ASC
        LIMIT 1
        """
    ).fetchone()


def review_candidate(
    conn: sqlite3.Connection,
    candidate_id: int,
    status: str,
    note: str | None = None,
) -> None:
    if status not in {"confirmed", "rejected", "unclear"}:
        raise ValueError("status must be confirmed, rejected, or unclear")

    ensure_schema(conn)
    row = conn.execute(
        "SELECT 1 FROM provenance_candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()

    if row is None:
        raise KeyError(f"No provenance candidate with id {candidate_id}")

    conn.execute(
        """
        UPDATE provenance_candidates
        SET review_status = ?,
            reviewer_note = ?,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, note, candidate_id),
    )
    conn.commit()


def summary(conn: sqlite3.Connection):
    ensure_schema(conn)
    return conn.execute(
        """
        SELECT evidence_type, review_status, COUNT(*) AS count
        FROM provenance_candidates
        GROUP BY evidence_type, review_status
        ORDER BY evidence_type, review_status
        """
    ).fetchall()


def export_confirmed(conn: sqlite3.Connection):
    ensure_schema(conn)
    return conn.execute(
        """
        SELECT
            workshop_id,
            source_title,
            evidence_type,
            classification,
            tools,
            evidence_snippet,
            created_at,
            updated_at,
            reviewer_note,
            reviewed_at
        FROM provenance_candidates
        WHERE review_status = 'confirmed'
        ORDER BY evidence_type, updated_at DESC, workshop_id
        """
    ).fetchall()
