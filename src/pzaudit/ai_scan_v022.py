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

    print("\nAI / GENERATIVE TOOL MENTIONS — CLASSIFIER v0.2.2")
    print(f"candidate items scanned:         {candidates:,}")
    print(f"explicit genAI development:      {summary['explicit_genai_dev']:,}")
    print(f"explicit generic AI development: {summary['explicit_ai_dev_unspecified']:,}")
    print(f"explicit vibe coding:            {summary['explicit_vibe_coding']:,}")
    print(f"AI art / asset mentions:         {summary['ai_art_or_asset_mention']:,}")
    print(f"AI policy / rejection:           {summary['ai_policy_or_rejection']:,}")
    print(f"gameplay AI:                     {summary['gameplay_ai']:,}")
    print(f"unclear tool mentions:           {summary['tool_mention_unclear']:,}")
    print(f"generic AI unclear:              {summary['generic_ai_unclear']:,}")

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
