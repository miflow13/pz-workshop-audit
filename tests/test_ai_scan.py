import sqlite3
from pzaudit.inspectors import classify_ai_mention, ai_mentions


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE mods (
            workshop_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            time_created INTEGER
        )
    """)
    return conn


def test_explicit_genai_dev():
    result = classify_ai_mention(
        "Example",
        "I made this mod using Claude to help write the Lua scripts.",
    )
    assert result is not None
    assert result["classification"] == "explicit_genai_dev"
    assert "Claude" in result["tools"]


def test_game_ai_is_ambiguous():
    result = classify_ai_mention(
        "Smarter Zombies",
        "Improves AI pathfinding and survivor behavior.",
    )
    assert result is not None
    assert result["classification"] == "gameplay_ai"


def test_prefilter_and_scan():
    conn = make_conn()
    conn.executemany(
        "INSERT INTO mods VALUES (?, ?, ?, ?)",
        [
            ("1", "Normal Mod", "Hand-made inventory tweak.", 1),
            ("2", "AI Zombies", "Improves AI pathfinding.", 2),
            ("3", "Claude Mod", "Made using Claude to write Lua.", 3),
        ],
    )
    summary, matches, candidates = ai_mentions(
        conn,
        limit=10,
        progress=False,
    )
    assert candidates == 2
    assert summary["explicit_genai_dev"] == 1
    assert summary["gameplay_ai"] == 1


def test_limit_does_not_limit_summary_or_write_database():
    conn = make_conn()
    conn.executemany('INSERT INTO mods VALUES (?, ?, ?, ?)', [
        ('1', 'AI generated image', None, 1),
        ('2', 'Example', 'I used Claude to write Lua code.', 2),
        ('3', 'Cursor', 'Changes the mouse cursor.', 3),
    ])
    before = conn.total_changes
    summary, matches, candidates = ai_mentions(conn, limit=0)
    assert candidates == 2
    assert sum(summary.values()) == 2
    assert matches == []
    assert conn.total_changes == before


def test_policy_and_gameplay_are_not_provenance():
    for text in ['Do not use AI artwork.', 'I coded improved zombie AI pathfinding.']:
        result = classify_ai_mention('', text)
        assert result['evidence_type'] is None


def test_distinct_disclosure_survives_policy_sentence():
    result = classify_ai_mention('', 'Do not use AI artwork. I used Claude to write Lua code.')
    assert result['evidence_type'] == 'code'


def test_general_development_has_unspecified_scope():
    result = classify_ai_mention('', 'AI services used during development.')
    assert result['evidence_type'] == 'development_general'
    assert result['provenance_classification'] == 'ai_development_scope_unspecified'
