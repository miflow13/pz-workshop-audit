import sqlite3

import pzaudit.provenance as provenance
from pzaudit.provenance import (
    _domain_evidence,
    refresh_pending_development_candidates,
)


def test_extinction_false_positive_is_removed():
    text = (
        "Use AI faction mod is strongly recommended for late phase of the game. "
        + ("ordinary zombie mechanics and world progression. " * 20)
        + "The implementation code handles corpse cleanup."
    )
    assert _domain_evidence(text) is None


def test_named_tool_and_code_in_same_window_is_code():
    text = "I used Claude to write and debug the Lua code for this mod."
    result = _domain_evidence(text)
    assert result is not None
    assert result[0] == "code"
    assert result[1] == "named_tool_code_claim"


def test_general_ai_development_is_not_code():
    text = (
        "Donations help cover dedicated server testing and "
        "AI services used during development."
    )
    result = _domain_evidence(text)
    assert result is not None
    assert result[0] == "development_general"
    assert result[1] == "ai_development_scope_unspecified"


def test_ai_cover_image_stays_assets():
    text = "If you like my dumbass AI generated cover image, please leave a like. Lua code is maintained separately."
    result = _domain_evidence(text)
    assert result is not None
    assert result[0] == "assets"


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE mods (
            workshop_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            time_created INTEGER,
            time_updated INTEGER
        );
    """)
    provenance.ensure_schema(conn)
    return conn


def test_refresh_preserves_reviewed_rows(monkeypatch):
    conn = make_conn()

    conn.execute(
        """
        INSERT INTO provenance_candidates(
            workshop_id,evidence_type,classification,evidence_snippet,
            review_status
        )
        VALUES
        ('reviewed','code','old','reviewed snippet','rejected'),
        ('pending','code','old','pending snippet','pending')
        """
    )

    conn.execute(
        """
        INSERT INTO mods VALUES
        ('new','New Mod','I used Claude to write the Lua code.',1,2)
        """
    )
    conn.commit()

    monkeypatch.setattr(
        provenance,
        "_tools_from_classifier",
        lambda title, description: "Claude",
    )

    removed, inserted, refreshed = refresh_pending_development_candidates(conn)

    assert removed == 1

    reviewed = conn.execute(
        "SELECT review_status FROM provenance_candidates WHERE workshop_id='reviewed'"
    ).fetchone()
    assert reviewed["review_status"] == "rejected"

    new = conn.execute(
        "SELECT evidence_type FROM provenance_candidates WHERE workshop_id='new'"
    ).fetchone()
    assert new["evidence_type"] == "code"
