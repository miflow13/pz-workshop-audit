import pytest
import pzaudit.provenance as provenance
from pzaudit.db import connect
from pzaudit.grouping import rebuild_groups
from pzaudit.review_cli import main


def test_refresh_all_preserves_reviews_and_census(tmp_path, monkeypatch, capsys):
    conn = connect(tmp_path / 'audit.db')
    provenance.ensure_schema(conn)
    descriptions = ['I used Claude to write Lua code.', 'AI generated image',
                    'AI-translated text', 'AI generated music',
                    'AI services used during development.']
    for i, description in enumerate(descriptions):
        conn.execute("INSERT INTO mods(workshop_id,title,description,raw_json) VALUES(?,?,?,'{}')",
                     (str(i), 'Example', description))
    conn.commit()
    provenance.extract_candidates(conn)
    for i, status in enumerate(['confirmed', 'rejected', 'unclear']):
        row = conn.execute('SELECT id FROM provenance_candidates WHERE workshop_id=?', (str(i),)).fetchone()
        provenance.review_candidate(conn, row['id'], status, 'Human note')
    reviewed = [tuple(r) for r in conn.execute("SELECT * FROM provenance_candidates WHERE review_status != 'pending'")]
    conn.execute("UPDATE mods SET time_updated=999 WHERE workshop_id='0'")
    conn.execute("INSERT INTO provenance_candidates(workshop_id,evidence_type,classification,evidence_snippet) VALUES('stale','assets','old','old')")
    conn.commit()
    census = [tuple(r) for r in conn.execute('SELECT * FROM mods')]
    rebuild_groups(conn, evidence_type='audio')
    conn.close()
    monkeypatch.setattr('sys.argv', ['pzaudit-review', '--db', str(tmp_path / 'audit.db'), 'refresh-all-pending'])
    main()
    assert 'preserved' in capsys.readouterr().out
    conn = connect(tmp_path / 'audit.db')
    assert [tuple(r) for r in conn.execute("SELECT * FROM provenance_candidates WHERE review_status != 'pending'")] == reviewed
    assert [tuple(r) for r in conn.execute('SELECT * FROM mods')] == census
    assert conn.execute("SELECT count(*) FROM provenance_candidates WHERE workshop_id='stale'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM provenance_candidates WHERE review_status='pending'").fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM provenance_group_members').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM provenance_groups').fetchone()[0] == 0
    assert provenance.refresh_all_pending_candidates(conn) == (2, 2, 3)


def test_refresh_failure_rolls_back(tmp_path, monkeypatch):
    conn = connect(tmp_path / 'audit.db')
    provenance.ensure_schema(conn)
    conn.execute("INSERT INTO mods(workshop_id,description,raw_json) VALUES('1','AI generated music','{}')")
    conn.commit()
    provenance.extract_candidates(conn)
    before = [tuple(r) for r in conn.execute('SELECT * FROM provenance_candidates')]
    def fail(*args):
        raise RuntimeError('classifier failed')
    monkeypatch.setattr(provenance, 'classify_ai_mention', fail)
    with pytest.raises(RuntimeError, match='classifier failed'):
        provenance.refresh_all_pending_candidates(conn)
    assert [tuple(r) for r in conn.execute('SELECT * FROM provenance_candidates')] == before


def test_title_only_and_changed_evidence(tmp_path):
    conn = connect(tmp_path / 'audit.db')
    conn.execute("INSERT INTO mods(workshop_id,title,raw_json) VALUES('1','AI generated image','{}')")
    conn.commit()
    assert provenance.extract_candidates(conn) == (1, 0)
    row = conn.execute('SELECT * FROM provenance_candidates').fetchone()
    provenance.review_candidate(conn, row['id'], 'rejected', 'Image only')
    conn.execute("UPDATE mods SET title='Example', description='I used Claude to write Lua code.'")
    conn.commit()
    assert provenance.refresh_all_pending_candidates(conn) == (0, 1, 0)
    assert conn.execute("SELECT review_status FROM provenance_candidates WHERE id=?", (row['id'],)).fetchone()[0] == 'rejected'
    assert conn.execute("SELECT evidence_type FROM provenance_candidates WHERE review_status='pending'").fetchone()[0] == 'code'


@pytest.mark.parametrize('evidence_type', ['code', 'development_general', 'assets', 'translation', 'audio'])
def test_refresh_removes_stale_pending_in_every_domain(tmp_path, evidence_type):
    conn = connect(tmp_path / 'audit.db')
    provenance.ensure_schema(conn)
    conn.execute("INSERT INTO provenance_candidates(workshop_id,evidence_type,classification,evidence_snippet) VALUES('gone',?,'old','old')", (evidence_type,))
    conn.commit()
    assert provenance.refresh_all_pending_candidates(conn) == (1, 0, 0)
    assert conn.execute('SELECT count(*) FROM provenance_candidates').fetchone()[0] == 0
