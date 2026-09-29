from __future__ import annotations

import re
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

TRANSLATION_RE = re.compile(
    r"\b(ai[- ]?(?:translated|translation|translations)|"
    r"(?:translated|translation|translations).{0,35}\b(?:ai|chatgpt|claude|gpt|llm)\b)\b",
    re.I | re.S,
)

AUDIO_RE = re.compile(
    r"\b(ai[- ]?(?:generated[- ]?)?(?:music|song|songs|voice|voices|audio)|"
    r"(?:music|song|songs|voice|voices|audio).{0,35}"
    r"\b(?:ai|chatgpt|claude|gpt|llm)\b)\b",
    re.I | re.S,
)

ASSET_RE = re.compile(
    r"\bai[- ]?(?:generated[- ]?)?(?:art|artwork|image|images|texture|textures|icon|icons|"
    r"thumbnail|thumbnails|illustration|illustrations|face|faces|cover image|cover art)\b"
    r"|\b(?:art|artwork|image|images|texture|textures|icon|icons|thumbnail|thumbnails|"
    r"illustration|illustrations|face|faces|cover image|cover art)\b.{0,35}"
    r"\b(?:ai|chatgpt|claude|gpt|llm)\b",
    re.I | re.S,
)

NAMED_TOOL_RE = re.compile(
    r"\b(chat\s*gpt|chatgpt|gpt(?:[-\s]?(?:3(?:\.5)?|4(?:o)?|5))?|claude|"
    r"(?:github\s+)?copilot|gemini|llms?|large language models?|"
    r"cursor\s+(?:ai|ide|editor))\b",
    re.I,
)

GENERIC_AI_RE = re.compile(
    r"\b(?:generative\s+ai|genai|artificial intelligence|ai)\b",
    re.I,
)

CODE_RE = re.compile(
    r"\b(code|coded|coding|script|scripts|lua|program|programming|implementation|"
    r"implemented|function|functions|debug|debugging|refactor|refactoring|source code)\b",
    re.I,
)

USE_RE = re.compile(
    r"\b(using|used|with|via|assisted|helped|generated|wrote|written|coded|built|"
    r"developed|prompted|pair[- ]programming|created|made|debugged|refactored)\b",
    re.I,
)

GENERAL_DEVELOPMENT_RE = re.compile(
    r"\b(?:ai|artificial intelligence|generative ai|genai)\b"
    r".{0,70}\b(?:used|services?|assisted|helped)\b"
    r".{0,70}\b(?:during|for|in)\b"
    r".{0,30}\b(?:development|developing)\b"
    r"|\b(?:used|using)\b.{0,40}\b(?:ai|artificial intelligence|generative ai|genai)\b"
    r".{0,70}\b(?:during|for|in)\b.{0,30}\b(?:development|developing)\b",
    re.I | re.S,
)

VIBE_RE = re.compile(r"\bvibe[-\s]?cod(?:e|ed|ing)\b", re.I)

# We intentionally use a fairly tight local window. The previous extractor
# matched "AI faction mod" near the top of a huge description with "code"
# hundreds/thousands of characters later.
LOCAL_RADIUS = 180


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


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _snippet(text: str, start: int, end: int, radius: int = 150) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def _local_window(text: str, match: re.Match[str], radius: int = LOCAL_RADIUS) -> tuple[str, int, int]:
    left = max(0, match.start() - radius)
    right = min(len(text), match.end() + radius)
    return text[left:right], left, right


def _find_code_claim(text: str) -> tuple[str, str, str] | None:
    """
    Return (evidence_type, classification, snippet) only when AI/tool use and
    coding language occur in the same local context.
    """
    vibe = VIBE_RE.search(text)
    if vibe:
        return (
            "code",
            "explicit_vibe_coding_claim",
            _snippet(text, vibe.start(), vibe.end()),
        )

    # Named tools are the strongest signal. Require code context AND a use verb
    # within +/- LOCAL_RADIUS of the actual tool mention.
    for tool in NAMED_TOOL_RE.finditer(text):
        window, left, _ = _local_window(text, tool)
        code = CODE_RE.search(window)
        use = USE_RE.search(window)

        if code and use:
            start = left + min(tool.start() - left, code.start(), use.start())
            end = left + max(tool.end() - left, code.end(), use.end())
            return (
                "code",
                "named_tool_code_claim",
                _snippet(text, start, end),
            )

    # Generic "AI" is much noisier. Require both code language and an explicit
    # use/action verb in the same tight window.
    for ai in GENERIC_AI_RE.finditer(text):
        window, left, _ = _local_window(text, ai)
        code = CODE_RE.search(window)
        use = USE_RE.search(window)

        if code and use:
            start = left + min(ai.start() - left, code.start(), use.start())
            end = left + max(ai.end() - left, code.end(), use.end())
            return (
                "code",
                "generic_ai_code_claim",
                _snippet(text, start, end),
            )

    # "AI services used during development" is real provenance evidence, but it
    # does not establish code generation or coding assistance.
    general = GENERAL_DEVELOPMENT_RE.search(text)
    if general:
        return (
            "development_general",
            "ai_development_scope_unspecified",
            _snippet(text, general.start(), general.end()),
        )

    return None


def _domain_evidence(text: str) -> tuple[str, str, str] | None:
    # Specific non-code provenance wins before generic development analysis.
    match = TRANSLATION_RE.search(text)
    if match:
        return (
            "translation",
            "ai_translation_claim",
            _snippet(text, match.start(), match.end()),
        )

    match = ASSET_RE.search(text)
    if match:
        return (
            "assets",
            "ai_asset_claim",
            _snippet(text, match.start(), match.end()),
        )

    match = AUDIO_RE.search(text)
    if match:
        return (
            "audio",
            "ai_audio_claim",
            _snippet(text, match.start(), match.end()),
        )

    return _find_code_claim(text)


def _tools_from_classifier(title: str | None, description: str | None) -> str:
    result = classify_ai_mention(title, description)
    if not result:
        return ""
    tools = result.get("tools") or []
    return ",".join(sorted(str(tool) for tool in tools))


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


def extract_candidates(conn: sqlite3.Connection) -> tuple[int, int]:
    ensure_schema(conn)
    inserted = 0
    refreshed = 0

    rows = conn.execute(
        """
        SELECT workshop_id, title, description, time_created, time_updated
        FROM mods
        WHERE description IS NOT NULL
          AND trim(description) != ''
        """
    )

    for row in rows:
        title = row["title"]
        description = row["description"]
        text = _clean(f"{title or ''} {description or ''}")

        domain = _domain_evidence(text)
        if not domain:
            continue

        evidence_type, classification, snippet = domain
        candidate = Candidate(
            workshop_id=str(row["workshop_id"]),
            evidence_type=evidence_type,
            classification=classification,
            tools=_tools_from_classifier(title, description),
            evidence_snippet=snippet,
            source_title=title,
            created_at=row["time_created"],
            updated_at=row["time_updated"],
        )

        if _insert_or_refresh(conn, candidate):
            inserted += 1
        else:
            refreshed += 1

    conn.commit()
    return inserted, refreshed


def refresh_pending_development_candidates(
    conn: sqlite3.Connection,
) -> tuple[int, int, int]:
    """
    Remove only *pending* code/development-general candidates produced by older
    extractor rules, then regenerate them using v0.3.2 proximity rules.

    Human-reviewed rows (confirmed/rejected/unclear) are preserved.

    Returns:
      removed_pending, new_candidates, refreshed_existing
    """
    ensure_schema(conn)

    before = conn.total_changes
    conn.execute(
        """
        DELETE FROM provenance_candidates
        WHERE review_status = 'pending'
          AND evidence_type IN ('code', 'development_general')
        """
    )
    removed = conn.total_changes - before
    conn.commit()

    inserted, refreshed = extract_candidates(conn)
    return removed, inserted, refreshed


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
