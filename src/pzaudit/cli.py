from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_DB_PATH, get_api_key
from .collector import collect
from .db import connect, counts
from .steam import SteamWorkshopClient
from .inspectors import overview, timeline, top_authors, top_tags, ai_mentions


def _db_path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pzaudit")
    parser.add_argument("--db", type=_db_path, default=DEFAULT_DB_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    collect_cmd = sub.add_parser("collect")
    collect_cmd.add_argument("--limit", type=int, default=None)
    collect_cmd.add_argument(
        "--page-size",
        type=int,
        default=100,
        choices=range(1, 101),
        metavar="1-100",
    )

    sub.add_parser("status")
    sub.add_parser("reset")

    inspect_cmd = sub.add_parser("inspect")
    inspect_sub = inspect_cmd.add_subparsers(
        dest="inspect_command",
        required=True,
    )

    inspect_sub.add_parser("overview")
    inspect_sub.add_parser("timeline")

    authors_cmd = inspect_sub.add_parser("authors")
    authors_cmd.add_argument("--limit", type=int, default=25)

    tags_cmd = inspect_sub.add_parser("tags")
    tags_cmd.add_argument("--limit", type=int, default=30)

    mentions_cmd = inspect_sub.add_parser("ai-mentions")
    mentions_cmd.add_argument("--limit", type=int, default=50)
    mentions_cmd.add_argument("--json", action="store_true")

    return parser


def cmd_collect(db: Path, limit: int | None, page_size: int) -> None:
    conn = connect(db)
    try:
        with SteamWorkshopClient(get_api_key()) as client:
            result = collect(
                conn,
                client,
                limit=limit,
                page_size=page_size,
            )
    except KeyboardInterrupt:
        print("\nInterrupted. Last fully committed Steam page is checkpointed.")
        return
    finally:
        conn.close()

    print(
        f"\nDone for this run: {result.seen} seen, "
        f"{result.inserted} inserted, {result.updated} updated."
    )


def cmd_status(db: Path) -> None:
    conn = connect(db)
    try:
        info = counts(conn)
    finally:
        conn.close()

    print("PROJECT ZOMBOID WORKSHOP CENSUS")
    print(f"local rows:       {info['local_rows']}")
    print(f"Steam total:      {info['steam_total'] or '?'}")
    print(f"pages committed:  {info['pages_committed']}")
    print(f"complete:         {'yes' if info['complete'] else 'no'}")
    cursor = str(info["cursor"])
    print(
        f"cursor:           {cursor[:70]}"
        f"{'…' if len(cursor) > 70 else ''}"
    )


def cmd_reset(db: Path) -> None:
    if db.exists():
        db.unlink()
    for suffix in ("-shm", "-wal"):
        sidecar = Path(str(db) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    print(f"Reset {db}")


def cmd_inspect(db: Path, args: argparse.Namespace) -> None:
    conn = connect(db)
    try:
        if args.inspect_command == "overview":
            data = overview(conn)
            print("PROJECT ZOMBOID WORKSHOP OVERVIEW")
            print(f"items:                 {data['items']:,}")
            print(f"unique authors:        {data['authors']:,}")
            print(f"oldest item:           {data['oldest']} UTC")
            print(f"newest item:           {data['newest']} UTC")
            print(f"missing titles:        {data['missing_titles']:,}")
            print(
                f"missing descriptions:  "
                f"{data['missing_descriptions']:,}"
            )

        elif args.inspect_command == "timeline":
            rows = timeline(conn)
            maximum = max((count for _, count in rows), default=1)
            print("WORKSHOP ITEMS CREATED PER YEAR")
            for year, count in rows:
                width = max(1, round(count / maximum * 36))
                print(f"{year}  {count:>6,}  {'█' * width}")

        elif args.inspect_command == "authors":
            print(f"TOP {args.limit} AUTHORS BY WORKSHOP ITEMS")
            for steam_id, count in top_authors(conn, args.limit):
                print(f"{count:>5,}  {steam_id}")

        elif args.inspect_command == "tags":
            print(f"TOP {args.limit} WORKSHOP TAGS")
            for tag, count in top_tags(conn, args.limit):
                print(f"{count:>6,}  {tag}")

        elif args.inspect_command == "ai-mentions":
            summary, matches, candidates = ai_mentions(
                conn,
                args.limit,
                progress=not args.json,
            )

            if args.json:
                print(
                    json.dumps(
                        {
                            "candidate_items": candidates,
                            "summary": dict(summary),
                            "matches": matches,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return

            print("\nAI / GENERATIVE TOOL MENTIONS")
            print(f"candidate items scanned: {candidates:,}")
            print(f"matching items:          {sum(summary.values()):,}")
            for label, count in sorted(summary.items()):
                print(f"{label}: {count:,}")
            print("\nScreening results require human provenance review.")

            for match in matches:
                tools = (
                    ", ".join(match["tools"])
                    if match["tools"]
                    else "-"
                )
                print(
                    f"\n[{match['classification']}] "
                    f"{match['workshop_id']} | "
                    f"{match['created']} | {match['title']}"
                )
                print(f"tools: {tools}")
                print(f"  {match['snippet']}")
    except KeyboardInterrupt:
        print("\nInspection interrupted cleanly. Database was not modified.")
    finally:
        conn.close()


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "collect":
        cmd_collect(args.db, args.limit, args.page_size)
    elif args.command == "status":
        cmd_status(args.db)
    elif args.command == "reset":
        cmd_reset(args.db)
    elif args.command == "inspect":
        cmd_inspect(args.db, args)


if __name__ == "__main__":
    main()
