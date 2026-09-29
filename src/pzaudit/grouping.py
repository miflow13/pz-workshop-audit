from __future__ import annotations

import hashlib
import html
import re
import sqlite3
from dataclasses import dataclass


SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_key TEXT NOT NULL UNIQUE,
    evidence_type TEXT NOT NULL,
    pattern_label TEXT NOT NULL,
    normalized_evidence TEXT NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    author_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rebuilt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provenance_group_members (
    group_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL UNIQUE,
    PRIMARY KEY(group_id, candidate_id),
    FOREIGN KEY(group_id) REFERENCES provenance_groups(id) ON DELETE CASCADE,
    FOREIGN KEY(candidate_id) REFERENCES provenance_candidates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_provenance_groups_type
ON provenance_groups(evidence_type);

CREATE INDEX IF NOT EXISTS idx_provenance_group_members_group
ON provenance_group_members(group_id);
"""

URL_RE = re.compile(r"https?://\S+", re.I)
BBCODE_RE = re.compile(r"\[[^\]]+\]")
WS_RE = re.compile(r"\s+")
NUMBER_RE = re.compile(r"\b\d+\b")

# High-value repeated disclosures get stable human-readable pattern labels.
KNOWN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ai_services_during_development",
        re.compile(r"\bai services used during development\b", re.I),
    ),
    (
        "ai_generated_code_claim",
        re.compile(
            r"\b(?:ai|chatgpt|claude|gpt|copilot|gemini|llm)"
            r".{0,50}\b(?:generated|wrote|coded)\b.{0,50}"
            r"\b(?:code|lua|script|scripts|functions?)\b",
            re.I | re.S,
        ),
    ),
    (
        "used_ai_for_code",
        re.compile(
            r"\b(?:used|using|with)\b.{0,30}"
            r"\b(?:ai|chatgpt|claude|gpt|copilot|gemini|llm|cursor)\b"
            r".{0,60}\b(?:code|coding|lua|script|scripts|debug|debugging|refactor|development)\b",
            re.I | re.S,
        ),
    ),
    (
        "vibe_coding_claim",
        re.compile(r"\bvibe[-\s]?cod(?:e|ed|ing)\b", re.I),
    ),
]


@dataclass(frozen=True)
class GroupRow:
    id: int
    group_key: str
    evidence_type: str
    pattern_label: str
    normalized_evidence: str
    member_count: int
    author_count: int


def ensure_group_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("PRAGMA foreign_keys=ON;\n" + SCHEMA)
    conn.commit()


def normalize_evidence(text: str) -> tuple[str, str]:
    """
    Return (pattern_label, normalized_evidence).

    Known repeated disclosures collapse to a stable anchor. Otherwise we
    normalize the evidence snippet enough to group near-identical boilerplate
    without pretending semantically different statements are equivalent.
    """
    raw = html.unescape(text or "")

    for label, pattern in KNOWN_PATTERNS:
        match = pattern.search(raw)
        if match:
            anchor = WS_RE.sub(" ", match.group(0).strip().lower())
            return label, anchor

    cleaned = URL_RE.sub(" ", raw)
    cleaned = BBCODE_RE.sub(" ", cleaned)
    cleaned = cleaned.lower()
    cleaned = NUMBER_RE.sub("<n>", cleaned)
    cleaned = WS_RE.sub(" ", cleaned).strip()

    # Evidence snippets contain context on either side. Keeping at most 500
    # normalized chars is enough for grouping while avoiding huge keys.
    if len(cleaned) > 500:
        cleaned = cleaned[:500]

    return "normalized_snippet", cleaned


def _group_key(
    evidence_type: str,
    pattern_label: str,
    normalized_evidence: str,
) -> str:
    payload = f"{evidence_type}\0{pattern_label}\0{normalized_evidence}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def rebuild_groups(
    conn: sqlite3.Connection,
    *,
    evidence_type: str = "code",
) -> tuple[int, int]:
    """
    Rebuild groups from currently-pending candidates of one evidence type.

    Existing review decisions are never changed. Group tables are review aids;
    rebuilding only changes group membership for candidates still pending.

    Returns (group_count, candidate_count).
    """
    ensure_group_schema(conn)

    # Delete only groups for this evidence type, preserving unrelated domains.
    group_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM provenance_groups WHERE evidence_type = ?",
            (evidence_type,),
        )
    ]
    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        conn.execute(
            f"DELETE FROM provenance_group_members WHERE group_id IN ({placeholders})",
            group_ids,
        )
        conn.execute(
            "DELETE FROM provenance_groups WHERE evidence_type = ?",
            (evidence_type,),
        )

    rows = conn.execute(
        """
        SELECT
            pc.id AS candidate_id,
            pc.evidence_type,
            pc.evidence_snippet,
            pc.workshop_id,
            m.creator_steam_id
        FROM provenance_candidates pc
        LEFT JOIN mods m
          ON m.workshop_id = pc.workshop_id
        WHERE pc.review_status = 'pending'
          AND pc.evidence_type = ?
        ORDER BY pc.id
        """,
        (evidence_type,),
    ).fetchall()

    buckets: dict[str, dict[str, object]] = {}

    for row in rows:
        label, normalized = normalize_evidence(row["evidence_snippet"])
        key = _group_key(evidence_type, label, normalized)

        bucket = buckets.setdefault(
            key,
            {
                "pattern_label": label,
                "normalized_evidence": normalized,
                "candidate_ids": [],
                "authors": set(),
            },
        )
        bucket["candidate_ids"].append(row["candidate_id"])

        creator = row["creator_steam_id"]
        if creator:
            bucket["authors"].add(str(creator))

    for key, bucket in buckets.items():
        cursor = conn.execute(
            """
            INSERT INTO provenance_groups(
                group_key,
                evidence_type,
                pattern_label,
                normalized_evidence,
                member_count,
                author_count,
                rebuilt_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                key,
                evidence_type,
                bucket["pattern_label"],
                bucket["normalized_evidence"],
                len(bucket["candidate_ids"]),
                len(bucket["authors"]),
            ),
        )
        group_id = cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO provenance_group_members(group_id, candidate_id)
            VALUES (?, ?)
            """,
            [(group_id, candidate_id) for candidate_id in bucket["candidate_ids"]],
        )

    conn.commit()
    return len(buckets), len(rows)


def list_groups(
    conn: sqlite3.Connection,
    *,
    evidence_type: str = "code",
    min_size: int = 2,
    limit: int = 50,
) -> list[sqlite3.Row]:
    ensure_group_schema(conn)
    return conn.execute(
        """
        SELECT *
        FROM provenance_groups
        WHERE evidence_type = ?
          AND member_count >= ?
        ORDER BY member_count DESC, author_count DESC, id
        LIMIT ?
        """,
        (evidence_type, min_size, limit),
    ).fetchall()


def get_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row | None:
    ensure_group_schema(conn)
    return conn.execute(
        "SELECT * FROM provenance_groups WHERE id = ?",
        (group_id,),
    ).fetchone()


def group_examples(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    limit: int = 5,
) -> list[sqlite3.Row]:
    ensure_group_schema(conn)
    return conn.execute(
        """
        SELECT
            pc.id AS candidate_id,
            pc.workshop_id,
            pc.source_title,
            pc.evidence_snippet,
            pc.tools,
            pc.created_at,
            pc.updated_at,
            m.creator_steam_id
        FROM provenance_group_members pgm
        JOIN provenance_candidates pc
          ON pc.id = pgm.candidate_id
        LEFT JOIN mods m
          ON m.workshop_id = pc.workshop_id
        WHERE pgm.group_id = ?
        ORDER BY pc.updated_at DESC, pc.id
        LIMIT ?
        """,
        (group_id, limit),
    ).fetchall()


def apply_group_review(
    conn: sqlite3.Connection,
    group_id: int,
    status: str,
    note: str | None = None,
) -> int:
    """
    Apply one review decision to every still-pending candidate in a group.

    Returns number of candidates changed.
    """
    if status not in {"confirmed", "rejected", "unclear"}:
        raise ValueError("status must be confirmed, rejected, or unclear")

    ensure_group_schema(conn)

    group = get_group(conn, group_id)
    if group is None:
        raise KeyError(f"No provenance group with id {group_id}")

    candidate_ids = [
        row["candidate_id"]
        for row in conn.execute(
            """
            SELECT pgm.candidate_id
            FROM provenance_group_members pgm
            JOIN provenance_candidates pc
              ON pc.id = pgm.candidate_id
            WHERE pgm.group_id = ?
              AND pc.review_status = 'pending'
            """,
            (group_id,),
        )
    ]

    if not candidate_ids:
        return 0

    placeholders = ",".join("?" for _ in candidate_ids)
    conn.execute(
        f"""
        UPDATE provenance_candidates
        SET review_status = ?,
            reviewer_note = ?,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
          AND review_status = 'pending'
        """,
        [status, note, *candidate_ids],
    )
    conn.commit()
    return len(candidate_ids)


def author_stats(
    conn: sqlite3.Connection,
    *,
    evidence_type: str = "code",
) -> list[sqlite3.Row]:
    """
    Show mod counts and unique-author counts by review status.

    This helps prevent a prolific author's repeated boilerplate from being
    mistaken for widespread independent adoption.
    """
    return conn.execute(
        """
        SELECT
            pc.review_status,
            COUNT(DISTINCT pc.workshop_id) AS mods,
            COUNT(DISTINCT m.creator_steam_id) AS authors
        FROM provenance_candidates pc
        LEFT JOIN mods m
          ON m.workshop_id = pc.workshop_id
        WHERE pc.evidence_type = ?
        GROUP BY pc.review_status
        ORDER BY pc.review_status
        """,
        (evidence_type,),
    ).fetchall()
