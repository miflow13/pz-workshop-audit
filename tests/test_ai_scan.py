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


def test_explicit_disclosure():
    result = classify_ai_mention(
        "Example",
        "I made this mod using Claude to help write the Lua scripts.",
    )
    assert result is not None
    assert result["classification"] == "explicit_disclosure"
    assert "Claude" in result["tools"]


def test_game_ai_is_ambiguous():
    result = classify_ai_mention(
        "Smarter Zombies",
        "Improves AI pathfinding and survivor behavior.",
    )
    assert result is not None
    assert result["classification"] == "ambiguous_ai"


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
    assert summary["explicit_disclosure"] == 1
    assert summary["ambiguous_ai"] == 1
