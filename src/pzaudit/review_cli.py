from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .grouping import (
    apply_group_review,
    author_stats,
    get_group,
    group_examples,
    list_groups,
    rebuild_groups,
)
from .provenance import (
    ensure_schema,
    export_confirmed,
    extract_candidates,
    next_pending,
    refresh_pending_development_candidates,
    refresh_all_pending_candidates,
    review_candidate,
    summary,
)

DEFAULT_DB = Path("data/pzaudit.db")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _date(ts: int | None) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def cmd_extract(conn: sqlite3.Connection) -> None:
    inserted, refreshed = extract_candidates(conn)
    print(f"new candidates:       {inserted:,}")
    print(f"existing refreshed:   {refreshed:,}")


def cmd_next(conn: sqlite3.Connection, evidence_type: str | None) -> None:
    row = next_pending(conn, evidence_type)
    if row is None:
        print("No pending provenance candidates.")
        return

    print(f"CANDIDATE #{row['id']}")
    print(f"Workshop ID:  {row['workshop_id']}")
    print(f"Title:        {row['source_title'] or '(untitled)'}")
    print(f"Evidence:     {row['evidence_type']}")
    print(f"Class:        {row['classification']}")
    print(f"Tools:        {row['tools'] or '-'}")
    print(f"Created:      {_date(row['created_at'])}")
    print(f"Updated:      {_date(row['updated_at'])}")
    print()
    print(row["evidence_snippet"])
    print()
    print("Review with:")
    print(f"  pzaudit-review confirm {row['id']}")
    print(f"  pzaudit-review reject {row['id']}")
    print(f"  pzaudit-review unclear {row['id']}")


def cmd_review(
    conn: sqlite3.Connection,
    candidate_id: int,
    status: str,
    note: str | None,
) -> None:
    review_candidate(conn, candidate_id, status, note)
    print(f"Candidate #{candidate_id} marked {status}.")


def cmd_summary(conn: sqlite3.Connection) -> None:
    rows = summary(conn)
    if not rows:
        print("No provenance candidates yet. Run: pzaudit-review extract")
        return

    print("PROVENANCE REVIEW SUMMARY")
    current = None
    for row in rows:
        if row["evidence_type"] != current:
            current = row["evidence_type"]
            print(f"\n{current.upper()}")
        print(f"  {row['review_status']:<10} {row['count']:>6,}")


def cmd_export(conn: sqlite3.Connection, output: Path) -> None:
    rows = export_confirmed(conn)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "workshop_id",
            "title",
            "evidence_type",
            "classification",
            "tools",
            "evidence_snippet",
            "created_at",
            "updated_at",
            "reviewer_note",
            "reviewed_at",
        ])
        for row in rows:
            writer.writerow([
                row["workshop_id"],
                row["source_title"],
                row["evidence_type"],
                row["classification"],
                row["tools"],
                row["evidence_snippet"],
                row["created_at"],
                row["updated_at"],
                row["reviewer_note"],
                row["reviewed_at"],
            ])
    print(f"Exported {len(rows):,} confirmed rows to {output}")


def cmd_build_groups(conn: sqlite3.Connection, evidence_type: str) -> None:
    groups, candidates = rebuild_groups(conn, evidence_type=evidence_type)
    print(
        f"Grouped {candidates:,} pending {evidence_type} candidates "
        f"into {groups:,} review groups."
    )


def cmd_groups(
    conn: sqlite3.Connection,
    evidence_type: str,
    min_size: int,
    limit: int,
) -> None:
    rows = list_groups(
        conn,
        evidence_type=evidence_type,
        min_size=min_size,
        limit=limit,
    )

    if not rows:
        print(
            "No matching groups. Run "
            f"`pzaudit-review build-groups --type {evidence_type}` first."
        )
        return

    print(
        f"{'GROUP':>7}  {'MODS':>5}  {'AUTHORS':>7}  PATTERN"
    )
    for row in rows:
        print(
            f"{row['id']:>7}  "
            f"{row['member_count']:>5}  "
            f"{row['author_count']:>7}  "
            f"{row['pattern_label']}"
        )


def cmd_group_show(
    conn: sqlite3.Connection,
    group_id: int,
    examples: int,
) -> None:
    group = get_group(conn, group_id)
    if group is None:
        raise SystemExit(f"No group #{group_id}")

    print(f"GROUP #{group['id']}")
    print(f"Evidence:       {group['evidence_type']}")
    print(f"Pattern:        {group['pattern_label']}")
    print(f"Mods:           {group['member_count']:,}")
    print(f"Unique authors: {group['author_count']:,}")
    print()
    print("Normalized evidence:")
    print(group["normalized_evidence"])

    rows = group_examples(conn, group_id, limit=examples)
    print(f"\nExamples ({len(rows)}):")

    for row in rows:
        print()
        print(
            f"Candidate #{row['candidate_id']} | "
            f"Workshop {row['workshop_id']} | "
            f"Author {row['creator_steam_id'] or '?'}"
        )
        print(row["source_title"] or "(untitled)")
        print(row["evidence_snippet"])


def cmd_group_review(
    conn: sqlite3.Connection,
    group_id: int,
    status: str,
    note: str | None,
) -> None:
    changed = apply_group_review(
        conn,
        group_id,
        status,
        note,
    )
    print(
        f"Marked {changed:,} pending candidates in group "
        f"#{group_id} as {status}."
    )


def cmd_author_stats(conn: sqlite3.Connection, evidence_type: str) -> None:
    rows = author_stats(conn, evidence_type=evidence_type)

    print(f"{evidence_type.upper()} PROVENANCE — MODS VS UNIQUE AUTHORS")
    print(f"{'STATUS':<12} {'MODS':>8} {'AUTHORS':>8}")
    for row in rows:
        print(
            f"{row['review_status']:<12} "
            f"{row['mods']:>8,} "
            f"{row['authors']:>8,}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pzaudit-review")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("extract")
    sub.add_parser("refresh-candidates")
    sub.add_parser("refresh-all-pending", help="Rebuild all pending evidence, preserving reviewed rows")

    next_cmd = sub.add_parser("next")
    next_cmd.add_argument(
        "--type",
        choices=["code", "development_general", "assets", "translation", "audio"],
        default=None,
    )

    for name, status in (
        ("confirm", "confirmed"),
        ("reject", "rejected"),
        ("unclear", "unclear"),
    ):
        cmd = sub.add_parser(name)
        cmd.add_argument("candidate_id", type=int)
        cmd.add_argument("--note", default=None)
        cmd.set_defaults(review_status=status)

    sub.add_parser("summary")

    export_cmd = sub.add_parser("export-confirmed")
    export_cmd.add_argument(
        "--output",
        type=Path,
        default=Path("data/confirmed_provenance.csv"),
    )

    build_groups = sub.add_parser("build-groups")
    build_groups.add_argument(
        "--type",
        choices=["code", "development_general", "assets", "translation", "audio"],
        default="code",
    )

    groups = sub.add_parser("groups")
    groups.add_argument(
        "--type",
        choices=["code", "development_general", "assets", "translation", "audio"],
        default="code",
    )
    groups.add_argument("--min-size", type=int, default=2)
    groups.add_argument("--limit", type=int, default=50)

    group = sub.add_parser("group")
    group.add_argument("group_id", type=int)
    group.add_argument("--examples", type=int, default=5)

    for name, status in (
        ("group-confirm", "confirmed"),
        ("group-reject", "rejected"),
        ("group-unclear", "unclear"),
    ):
        cmd = sub.add_parser(name)
        cmd.add_argument("group_id", type=int)
        cmd.add_argument("--note", default=None)
        cmd.set_defaults(group_review_status=status)

    authors = sub.add_parser("author-stats")
    authors.add_argument(
        "--type",
        choices=["code", "development_general", "assets", "translation", "audio"],
        default="code",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()
    conn = _connect(args.db)

    try:
        ensure_schema(conn)

        if args.command == "extract":
            cmd_extract(conn)
        elif args.command == "refresh-all-pending":
            removed, inserted, existing = refresh_all_pending_candidates(conn)
            print(f"Pending rows removed: {removed:,}")
            print(f"New candidates inserted: {inserted:,}")
            print(f"Existing reviewed matches preserved: {existing:,}")
            print("Reviewed rows were preserved. Rebuild groups before grouped review.")
        elif args.command == "refresh-candidates":
            removed, inserted, refreshed = refresh_pending_development_candidates(conn)
            print("PROVENANCE CANDIDATE REFRESH v0.3.2")
            print(f"old pending code/development rows removed: {removed:,}")
            print(f"new candidates inserted:                   {inserted:,}")
            print(f"existing candidates refreshed:             {refreshed:,}")
            print("Reviewed rows were preserved.")
        elif args.command == "next":
            cmd_next(conn, args.type)
        elif args.command in {"confirm", "reject", "unclear"}:
            cmd_review(
                conn,
                args.candidate_id,
                args.review_status,
                args.note,
            )
        elif args.command == "summary":
            cmd_summary(conn)
        elif args.command == "export-confirmed":
            cmd_export(conn, args.output)
        elif args.command == "build-groups":
            cmd_build_groups(conn, args.type)
        elif args.command == "groups":
            cmd_groups(
                conn,
                args.type,
                args.min_size,
                args.limit,
            )
        elif args.command == "group":
            cmd_group_show(
                conn,
                args.group_id,
                args.examples,
            )
        elif args.command in {
            "group-confirm",
            "group-reject",
            "group-unclear",
        }:
            cmd_group_review(
                conn,
                args.group_id,
                args.group_review_status,
                args.note,
            )
        elif args.command == "author-stats":
            cmd_author_stats(conn, args.type)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
