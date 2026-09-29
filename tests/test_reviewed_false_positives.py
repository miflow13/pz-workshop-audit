"""Regressions found while manually reviewing provenance groups."""

import sqlite3

from pzaudit.inspectors import classify_ai_mention
from pzaudit.provenance import extract_candidates, refresh_all_pending_candidates, review_candidate


def test_artwork_disclosure_does_not_become_code():
    result = classify_ai_mention(
        'Nightshade menu theme',
        'This menu theme uses AI-assisted artwork, curated, edited, arranged, and implemented by me for Project Zomboid.',
    )
    assert result['evidence_type'] == 'assets'
    assert result['provenance_classification'] == 'ai_asset_claim'


def test_explicit_ai_denial_is_not_provenance():
    result = classify_ai_mention(
        'Simple Items: Espresso',
        'This mod does not include any AI-generated code or AI-assistance whatsoever.',
    )
    assert result['evidence_type'] is None


def test_claude_code_user_integration_is_not_development_provenance():
    result = classify_ai_mention(
        'Arkavo Game-RL',
        'Connect with Claude Code for natural language survivor management. '
        '[h1]Connect with Claude Code[/h1] [*]Install Claude Code: https://claude.ai/code '
        '[*]Load Project Zomboid [*]Create a project folder and add MCP server: '
        '[code]claude mcp add game-rl[/code]',
    )
    assert result['evidence_type'] is None


def test_claude_code_helped_make_a_mod_conversion():
    result = classify_ai_mention(
        'NotAlone NPC Mod Build 42 conversion',
        "Full transparency: I made this build 42 conversion with Claude Code's huge help.",
    )
    assert result['evidence_type'] == 'code'


def test_other_vibecoded_version_is_not_this_mods_provenance():
    result = classify_ai_mention(
        'More Traits Legacy',
        'Alternatively use this until it fully breaks or try finding AI-vibecoded "fixed" version on the workshop.',
    )
    assert result['evidence_type'] is None


def test_refresh_restores_asset_candidate_without_changing_rejected_code_review():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE mods(workshop_id TEXT PRIMARY KEY, title TEXT, description TEXT, time_created INTEGER, time_updated INTEGER)')
    conn.execute('INSERT INTO mods VALUES (?, ?, ?, 1, 2)', (
        '3734707989', 'Nightshade menu theme',
        'This menu theme uses AI-assisted artwork, curated, edited, arranged, and implemented by me for Project Zomboid.',
    ))
    conn.commit()
    extract_candidates(conn)
    original = conn.execute('SELECT * FROM provenance_candidates').fetchone()
    assert original['evidence_type'] == 'assets'
    conn.execute("INSERT INTO provenance_candidates(workshop_id,evidence_type,classification,evidence_snippet) VALUES('3734707989','code','generic_ai_code_claim','old snippet')")
    stale = conn.execute("SELECT id FROM provenance_candidates WHERE evidence_type='code'").fetchone()['id']
    conn.commit()
    review_candidate(conn, stale, 'rejected', 'Artwork, not code')
    reviewed_before = tuple(conn.execute('SELECT * FROM provenance_candidates WHERE id=?', (stale,)).fetchone())
    refresh_all_pending_candidates(conn)
    assert tuple(conn.execute('SELECT * FROM provenance_candidates WHERE id=?', (stale,)).fetchone()) == reviewed_before
    pending = conn.execute("SELECT * FROM provenance_candidates WHERE review_status='pending'").fetchall()
    assert len(pending) == 1 and pending[0]['evidence_type'] == 'assets'
