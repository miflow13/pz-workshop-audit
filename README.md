# pzaudit v0.3.4

Project Zomboid Steam Workshop census and human-reviewed AI provenance tooling.
The census schema and collected Workshop records remain unchanged.

Version 0.3.4 corrects false code candidates caused by AI-artwork disclosures,
explicit AI-use denials, Claude Code integrations, and references to other
vibecoded mods. A pending refresh can now place AI-assisted artwork in the
assets queue. Reviewed decisions remain unchanged.

## Install / upgrade

After merging the cleanup PR, update your checkout and reinstall in your existing
virtual environment:

```bash
git pull --ff-only
pip install -e ".[dev]"
python -m pytest
```

No census migration or recollection is needed. Do not run `pzaudit reset` to upgrade.

## Rebuild the pending review queue

```bash
pzaudit-review --db data/pzaudit.db refresh-all-pending
pzaudit-review --db data/pzaudit.db summary
pzaudit-review --db data/pzaudit.db build-groups --type code
pzaudit-review --db data/pzaudit.db groups --type code --min-size 2
```

`refresh-all-pending` atomically removes every pending candidate and scans all
current census titles/descriptions with the current classifier. It includes
code, general development, translation, assets, and audio. An extraction failure
rolls back the refresh. It never updates the `mods` or `crawl_state` tables.

All confirmed, rejected, and unclear candidate rows remain unchanged, including
IDs, evidence, notes, and timestamps. Identical reviewed evidence is not reopened.
Changed evidence or classifier-generated snippets may produce a new pending candidate alongside the historical
reviewed row; reviews are evidence-specific, not blanket decisions about a mod.
Pending candidate IDs are replaced, so old pending IDs should not be reused.

Refresh invalidates cached review groups to prevent stale membership and counts.
Rebuild groups for each evidence type you want to review (`code`,
`development_general`, `translation`, `assets`, or `audio`). This does not undo
previous group decisions, which are stored on the reviewed candidates.

The older `refresh-candidates` command remains available for replacing only
pending code/general-development rows; it also invalidates group caches.
`extract` adds or refreshes current matches without removing stale pending rows.

## Inspect and review

```bash
pzaudit --db data/pzaudit.db inspect overview
pzaudit --db data/pzaudit.db inspect ai-mentions --json
pzaudit-review --db data/pzaudit.db next
pzaudit-review --db data/pzaudit.db confirm 123 --note "Explicit author statement"
pzaudit-review --db data/pzaudit.db export-confirmed
```

The scanner and provenance extractor share one classifier. Screening labels such
as `explicit_genai_dev` remain distinct from provenance classifications such as
`named_tool_code_claim`. Coding evidence requires nearby tool/AI, action, and
coding language. Unspecified development assistance is `development_general`;
translation, assets, and audio stay separate. Gameplay AI and rejection/policy
mentions are screening results, not provenance candidates.

These are heuristic candidates requiring human review. The existing one-candidate
per item precedence is translation, assets, audio, then code/general development;
mixed-domain descriptions are not exhaustive inventories of AI use.
