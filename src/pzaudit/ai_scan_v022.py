from __future__ import annotations
import argparse
from pathlib import Path
from .inspectors import ai_mentions

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/pzaudit.db"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        summary, matches, candidates = ai_mentions(conn, args.limit)
    except KeyboardInterrupt:
        print("\nInspection interrupted cleanly. Database was not modified.")
        return
    finally:
        conn.close()

    print("\nAI / GENERATIVE TOOL MENTIONS")
    print(f"candidate items scanned: {candidates:,}")
    for label, count in sorted(summary.items()):
        print(f"{label}: {count:,}")

    for match in matches:
        tools = ", ".join(match["tools"]) if match["tools"] else "-"
        print(
            f"\n[{match['classification']}] {match['workshop_id']} "
            f"| created {match['created']} | updated {match['updated']} "
            f"| {match['title']}"
        )
        print(f"tools: {tools}")
        print(f"  {match['snippet']}")

if __name__ == "__main__":
    main()
