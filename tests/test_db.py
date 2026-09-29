from pathlib import Path

from pzaudit.db import connect, counts, save_page


def detail(workshop_id: str, title: str = "Example") -> dict:
    return {
        "publishedfileid": workshop_id,
        "creator": "76561198000000000",
        "title": title,
        "file_description": "Description",
        "time_created": 1700000000,
        "time_updated": 1700000100,
        "file_type": 0,
        "file_size": 1234,
        "visibility": 0,
        "subscriptions": 10,
        "lifetime_subscriptions": 20,
        "favorited": 2,
        "lifetime_favorited": 3,
        "tags": [{"tag": "Mod"}],
    }


def test_page_upsert_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")

    inserted, updated = save_page(
        conn,
        [detail("123")],
        next_cursor="cursor-2",
        steam_total=100,
        complete=False,
    )
    assert (inserted, updated) == (1, 0)

    inserted, updated = save_page(
        conn,
        [detail("123", title="Changed")],
        next_cursor="cursor-3",
        steam_total=100,
        complete=False,
    )
    assert (inserted, updated) == (0, 1)

    row = conn.execute(
        "SELECT title FROM mods WHERE workshop_id = '123'"
    ).fetchone()
    assert row["title"] == "Changed"
    assert counts(conn)["local_rows"] == 1
