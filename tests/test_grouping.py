import sqlite3

from pzaudit.grouping import (
    apply_group_review,
    author_stats,
    group_examples,
    list_groups,
    normalize_evidence,
    rebuild_groups,
)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE mods (
            workshop_id TEXT PRIMARY KEY,
            creator_steam_id TEXT
        );

        CREATE TABLE provenance_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workshop_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            classification TEXT NOT NULL,
            tools TEXT NOT NULL DEFAULT '',
            evidence_snippet TEXT NOT NULL,
            source_title TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            review_status TEXT NOT NULL DEFAULT 'pending',
            reviewer_note TEXT,
            reviewed_at TEXT
        );
    """)

    return conn


def add_candidate(
    conn,
    workshop_id,
    author,
    snippet,
    *,
    evidence_type="code",
    status="pending",
    title="Example",
):
    conn.execute(
        "INSERT OR REPLACE INTO mods VALUES (?, ?)",
        (workshop_id, author),
    )
    conn.execute(
        """
        INSERT INTO provenance_candidates(
            workshop_id,
            evidence_type,
            classification,
            evidence_snippet,
            source_title,
            review_status
        )
        VALUES (?, ?, 'claim', ?, ?, ?)
        """,
        (
            workshop_id,
            evidence_type,
            snippet,
            title,
            status,
        ),
    )
    conn.commit()


def test_known_boilerplate_normalizes_together():
    a = (
        "Donations help cover server costs and AI services used during "
        "development. Thank you!"
    )
    b = (
        "Different prefix. AI services used during development. "
        "Different suffix."
    )

    label_a, normalized_a = normalize_evidence(a)
    label_b, normalized_b = normalize_evidence(b)

    assert label_a == "ai_services_during_development"
    assert label_b == "ai_services_during_development"
    assert normalized_a == normalized_b


def test_grouping_collapses_repeated_boilerplate():
    conn = make_conn()

    add_candidate(
        conn,
        "1",
        "author-a",
        "AI services used during development.",
    )
    add_candidate(
        conn,
        "2",
        "author-a",
        "Prefix AI services used during development. Suffix",
    )
    add_candidate(
        conn,
        "3",
        "author-b",
        "AI services used during development.",
    )

    groups, candidates = rebuild_groups(conn)

    assert candidates == 3
    assert groups == 1

    rows = list_groups(conn, min_size=2)
    assert len(rows) == 1
    assert rows[0]["member_count"] == 3
    assert rows[0]["author_count"] == 2


def test_group_review_only_changes_pending_members():
    conn = make_conn()

    add_candidate(
        conn,
        "1",
        "a",
        "AI services used during development.",
    )
    add_candidate(
        conn,
        "2",
        "b",
        "AI services used during development.",
    )

    rebuild_groups(conn)
    group = list_groups(conn, min_size=2)[0]

    changed = apply_group_review(
        conn,
        group["id"],
        "unclear",
        "Scope unspecified.",
    )

    assert changed == 2

    statuses = [
        row["review_status"]
        for row in conn.execute(
            "SELECT review_status FROM provenance_candidates ORDER BY id"
        )
    ]
    assert statuses == ["unclear", "unclear"]


def test_author_stats_distinguishes_mods_and_authors():
    conn = make_conn()

    add_candidate(
        conn,
        "1",
        "same-author",
        "AI services used during development.",
        status="unclear",
    )
    add_candidate(
        conn,
        "2",
        "same-author",
        "AI services used during development.",
        status="unclear",
    )
    add_candidate(
        conn,
        "3",
        "other-author",
        "Used Claude for Lua code.",
        status="confirmed",
    )

    rows = {
        row["review_status"]: (row["mods"], row["authors"])
        for row in author_stats(conn)
    }

    assert rows["unclear"] == (2, 1)
    assert rows["confirmed"] == (1, 1)
