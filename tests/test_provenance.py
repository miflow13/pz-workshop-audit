import sqlite3
from pzaudit.provenance import (
    extract_candidates, next_pending, review_candidate, summary
)

def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE mods (
            workshop_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            time_created INTEGER,
            time_updated INTEGER
        )
    """)
    return conn

def insert(conn, wid, title, description, created=1, updated=2):
    conn.execute(
        "INSERT INTO mods VALUES (?, ?, ?, ?, ?)",
        (wid, title, description, created, updated),
    )
    conn.commit()

def test_extract_separates_assets_from_code(monkeypatch):
    conn = make_conn()
    insert(conn, "1", "Cover Image Example",
           "This mod uses an AI generated cover image. The Lua code is mine.")
    monkeypatch.setattr(
        "pzaudit.provenance.classify_ai_mention",
        lambda title, desc: {"tools": []},
    )
    inserted, refreshed = extract_candidates(conn)
    assert (inserted, refreshed) == (1, 0)
    row = conn.execute("SELECT * FROM provenance_candidates").fetchone()
    assert row["evidence_type"] == "assets"

def test_translation_candidate(monkeypatch):
    conn = make_conn()
    insert(conn, "2", "Translated Mod",
           "This mod is AI-translated to all available languages.")
    monkeypatch.setattr(
        "pzaudit.provenance.classify_ai_mention",
        lambda title, desc: {"tools": []},
    )
    extract_candidates(conn)
    row = conn.execute("SELECT * FROM provenance_candidates").fetchone()
    assert row["evidence_type"] == "translation"

def test_audio_candidate(monkeypatch):
    conn = make_conn()
    insert(conn, "3", "Music Mod",
           "Includes AI generated music for the cassette collection.")
    monkeypatch.setattr(
        "pzaudit.provenance.classify_ai_mention",
        lambda title, desc: {"tools": []},
    )
    extract_candidates(conn)
    row = conn.execute("SELECT * FROM provenance_candidates").fetchone()
    assert row["evidence_type"] == "audio"

def test_code_candidate_requires_context(monkeypatch):
    conn = make_conn()
    insert(conn, "4", "Code Mod",
           "I used Claude while developing and debugging the Lua code.")
    monkeypatch.setattr(
        "pzaudit.provenance.classify_ai_mention",
        lambda title, desc: {"tools": ["Claude"]},
    )
    extract_candidates(conn)
    row = conn.execute("SELECT * FROM provenance_candidates").fetchone()
    assert row["evidence_type"] == "code"
    assert row["tools"] == "Claude"

def test_review_workflow(monkeypatch):
    conn = make_conn()
    insert(conn, "5", "Code Mod",
           "I used ChatGPT while developing the Lua scripts.")
    monkeypatch.setattr(
        "pzaudit.provenance.classify_ai_mention",
        lambda title, desc: {"tools": ["ChatGPT"]},
    )
    extract_candidates(conn)
    row = next_pending(conn)
    assert row is not None
    review_candidate(conn, row["id"], "confirmed", "Explicit author statement.")
    reviewed = conn.execute(
        "SELECT * FROM provenance_candidates WHERE id = ?", (row["id"],)
    ).fetchone()
    assert reviewed["review_status"] == "confirmed"
    counts = {
        (r["evidence_type"], r["review_status"]): r["count"]
        for r in summary(conn)
    }
    assert counts[("code", "confirmed")] == 1
