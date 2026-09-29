# pzaudit v0.3.2 — integrated proximity + grouped review

This combines the v0.3.2 proximity-aware provenance extractor with the v0.3.1 grouped-review workflow.

## Install

Copy these files into the existing project:

```text
src/pzaudit/provenance.py
src/pzaudit/grouping.py
src/pzaudit/review_cli.py
```

Keep your current `inspectors.py`.

Then reinstall:

```bash
pip install -e ".[dev]"
```

## Refresh the polluted pending queue

```bash
pzaudit-review refresh-candidates
pzaudit-review summary
```

This removes and regenerates only pending `code` / `development_general` candidates. Reviewed rows are preserved.

## Rebuild groups

```bash
pzaudit-review build-groups --type code
pzaudit-review groups --type code --min-size 2
```

The extractor now requires AI/tool and coding language to appear in the same local context. Vague phrases such as `AI services used during development` go to `development_general` rather than `code`.
# pz-workshop-audit
