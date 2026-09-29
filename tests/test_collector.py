from pathlib import Path

from pzaudit.collector import collect
from pzaudit.db import connect, counts
from pzaudit.steam import QueryPage


def item(n: int) -> dict:
    return {
        "publishedfileid": str(n),
        "title": f"Mod {n}",
        "tags": [],
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def query_page(self, cursor: str, *, num_per_page: int = 100) -> QueryPage:
        self.calls.append(cursor)
        if cursor == "*":
            return QueryPage([item(1), item(2)], "next", 3)
        if cursor == "next":
            return QueryPage([item(3)], "", 3)
        raise AssertionError(cursor)


def test_collect_reaches_completion(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    client = FakeClient()

    result = collect(conn, client, page_size=2)

    assert result.seen == 3
    assert counts(conn)["local_rows"] == 3
    assert counts(conn)["complete"] is True
    assert client.calls == ["*", "next"]
