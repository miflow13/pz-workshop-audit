# Static Analysis Validation Guide

This document is for collaborators who want to test `pzaudit` against software whose development history they actually know.

The goal is **not** to build a magic "AI detector." The goal is to test whether measurable code characteristics tell us anything useful about development process when we have known provenance to compare against.

## What this project is studying

The research question started as:

> How common is AI-assisted coding in Project Zomboid mods, and can we distinguish careful AI-assisted development from code that was generated and shipped with little understanding, review, or testing?

Those are separate questions.

Phase 1 measures **publicly disclosed provenance** from Steam Workshop metadata. Phase 2 will inspect actual source files and test whether static-analysis signals are meaningful when compared with known-provenance software.

Throughout the project, these terms are kept separate:

- **AI-assisted** — AI helped with some part of development, but a human still authors, reviews, tests, or substantially edits the implementation.
- **AI-generated / AI-dominant** — a model generated substantial implementation code. This still does not imply poor quality.
- **Vibe coded** — prompt-dominant development where substantial implementation is generated and the developer primarily directs, executes, and validates it rather than manually authoring the implementation.
- **Carelessly shipped AI output** — generated code is published with little understanding, testing, or review. This is a quality/process question, not something we assume from AI use alone.

Static code style alone is not treated as proof of any of these categories.

---

## Phase 1: Workshop census

The collector queried Steam's Workshop API for Project Zomboid (App ID `108600`) using cursor pagination and stored the returned metadata in SQLite.

Census snapshot:

| Metric | Result |
| --- | ---: |
| Workshop items | 64,908 |
| Unique Workshop IDs | 64,908 |
| Unique creators | 26,396 |
| Oldest item | August 2015 |
| Latest item in the census | September 2026 |

The collector stores titles, descriptions, creator IDs, timestamps, tags, file metadata, engagement metadata, and the raw Steam API JSON. The crawl is resumable.

No HTML scraping is required for the census.

---

## Phase 1: Provenance screening

A naive search for terms such as `AI`, `ChatGPT`, `Claude`, `Copilot`, `Gemini`, `LLM`, `Cursor`, and `vibe coding` produced many false positives.

Examples include:

- gameplay/NPC/pathfinding AI
- AI-generated cover art or other assets
- AI-generated music/audio
- AI translation
- anti-AI or "no AI used" statements
- name collisions such as Claude or Gemini
- vague statements such as "AI services used during development"

The classifier therefore separates evidence domains instead of treating every AI mention as code provenance:

- code
- general development
- assets
- translation
- audio
- gameplay AI
- policy/rejection statements
- ambiguous tool mentions

Coding candidates require AI/tool language, an action/use signal, and programming-related language in the same local context. Human review remains required.

After progressively tightening the screening rules, the code-review queue was reduced to **106 candidates**.

Current review recommendations for those 106 candidates:

| Recommendation | Count |
| --- | ---: |
| Confirm | 87 |
| Reject | 13 |
| Unclear | 6 |

At the time these Phase 1 figures were produced, these were review recommendations rather than final committed review decisions.

"Confirm" here means that the public metadata provides evidence that generative AI was used in coding-related work. It does **not** mean the whole mod was AI-generated, low quality, unsafe, or vibe coded.

---

## Preliminary timeline results

Among the 87 recommended confirmations, 85 belong to Workshop items created from 2023 onward.

| Creation year | Recommended-confirmed disclosures | All Workshop items created that year | Share of all Workshop items |
| --- | ---: | ---: | ---: |
| 2023 | 0 | 10,541 | 0.000% |
| 2024 | 2 | 9,736 | 0.021% |
| 2025 | 6 | 9,924 | 0.060% |
| 2026 | 77 | 24,378 | 0.316% |
| **2023–2026** | **85** | **54,579** | **0.156%** |

The creation-year pattern is notable: **77 of the 85 post-2022 recommended confirmations are attached to items created in 2026**.

Important limitation: an item's creation year does not prove that AI was used in that same year. An older mod can later be updated using AI, and the current Workshop description can also be edited after publication.

These figures measure **detectable public disclosure**, not total AI use.

---

## Metadata proxy analysis

Steam does not expose a clean "contains source code" Workshop tag, so two metadata-based proxy cohorts were tested.

### Strict proxy

| Year | AI-code disclosures | Proxy cohort | Disclosure share |
| --- | ---: | ---: | ---: |
| 2023 | 0 | 1,558 | 0.000% |
| 2024 | 1 | 1,648 | 0.061% |
| 2025 | 2 | 2,274 | 0.088% |
| 2026 | 42 | 6,584 | 0.638% |
| **Total** | **45** | **12,064** | **0.373%** |

### Broad proxy

| Year | AI-code disclosures | Proxy cohort | Disclosure share |
| --- | ---: | ---: | ---: |
| 2023 | 0 | 3,369 | 0.000% |
| 2024 | 2 | 3,325 | 0.060% |
| 2025 | 6 | 3,740 | 0.160% |
| 2026 | 57 | 9,466 | 0.602% |
| **Total** | **65** | **19,900** | **0.327%** |

The exact rate depends on the denominator, but the 2026 increase survives both proxy definitions.

The proxies are **not** the final denominator. Of the 85 post-2022 recommended confirmations, the strict proxy captures 45 and the broad proxy captures 65. That means even the broad metadata proxy misses 20 known AI-coding disclosure cases.

That is one reason Phase 2 moves to actual files instead of relying on Steam tags.

---

## What Phase 1 does *not* establish

Phase 1 does not tell us:

- how many authors used AI without disclosing it
- whether a disclosed AI-assisted mod is good or bad
- whether the author understands the generated code
- whether the code was adequately tested
- whether the mod is safe
- whether a mod is "vibe coded"
- whether code can be identified as AI-written from style alone

A public disclosure is provenance evidence, not a quality score.

---

## Phase 2: Source-level analysis

The next phase will inspect actual source files rather than infer code-bearing status from Workshop metadata.

The first practical goal is to identify genuinely code-bearing items, starting with source types such as `.lua`, and then build comparison cohorts.

Planned analysis areas include:

### File and project structure

- source-file inventory
- language/extension mix
- lines of code
- file and function size
- module organization
- dependency/import patterns

### Complexity and maintainability

- cyclomatic/branch complexity where parsers support it
- nesting depth
- function length
- duplication/repeated blocks
- comment and documentation density
- parse errors or malformed source
- unusually large or monolithic files

### Implementation behavior

Where language/tooling support allows it:

- global state and global writes
- event-hook usage
- dynamic evaluation/loading
- file I/O
- network interaction
- process/system interaction
- serialization/deserialization
- error handling
- defensive validation
- potentially security-relevant API usage

A flagged API call is **not** automatically malicious or unsafe. Context and manual review are required.

### Testing and development signals

Where observable from the supplied project:

- automated tests
- test-to-source ratio
- lint/static-check configuration
- CI configuration
- type checking
- assertions and input validation
- explicit error handling
- documentation/readme quality

These are descriptive metrics, not an AI score.

---

## Why your project is useful

A major problem in this research is ground truth.

For random Workshop code, we usually do not know exactly how it was produced. Your own project is different because **you know its development history**.

That lets us ask a much better question:

> When we already know how software was built, do the static-analysis signals actually line up with that history?

If they do not, that is just as important a finding as if they do.

A useful validation project can therefore help us detect:

- false "AI-like" signals in human-written code
- human-like metrics in heavily AI-assisted code
- signals that correlate with testing/review rather than AI provenance
- metrics that are too noisy to use responsibly
- language-specific effects that would otherwise be mistaken for AI effects

---

## Ground-truth information that would help

If you are comfortable sharing it, please record the following for the version/commit you test:

1. **Repository or commit identifier** — enough to make the analyzed version reproducible.
2. **Primary language(s)**.
3. **Development provenance**, in your own words:
   - no generative AI used
   - AI used for questions/explanations only
   - AI used for small snippets
   - AI used for substantial implementation
   - prompt-dominant/vibe-coded workflow
   - mixed workflow
4. **AI tools used**, if any.
5. **Which parts/files were AI-assisted**, if known.
6. **How much generated code was manually rewritten or reviewed**.
7. **Testing performed** — automated, manual, both, or none.
8. **Code review** — self-review, peer review, or none.
9. Anything unusual about the project that could distort metrics, such as generated files, vendored dependencies, minified code, migrations, or large data files.

You do not need to disclose prompts, private conversations, API keys, secrets, or personal information.

---

## Current tooling status

The repository now includes a local static-analysis runner for arbitrary source trees.

Install or upgrade the project:

```bash
git pull --ff-only
pip install -e ".[dev]"
python -m pytest
```

Run an aggregate-only analysis locally:

```bash
pzaudit analyze /path/to/project --output pzaudit-report.json
```

That is the recommended collaborator workflow. The source tree stays on your machine. By default the report contains aggregate metrics only and does **not** include source text or source-file paths.

If you are comfortable sharing relative file paths and per-file metrics, opt in explicitly:

```bash
pzaudit analyze /path/to/project \
  --output pzaudit-report.json \
  --include-file-metrics
```

The current report includes source inventory, line counts, function/class counts, heuristic branch-point counts, testing/CI/configuration signals, and counts of selected process-execution, dynamic-loading, filesystem, and network API usage.

The analyzer also writes a deterministic source fingerprint for the analyzed source snapshot. This helps us verify that two reports refer to the same source without uploading the source itself.

Please send back:

- `pzaudit-report.json`
- the exact repository commit/version that was analyzed
- the ground-truth development notes described above
- any constraints on publication or attribution

If you prefer, you can keep the source completely private. We do not need a packaged mod or repository archive to compare the aggregate report against your known provenance.

---

## Interpretation rules

When we analyze your project, we will follow these rules:

1. **No single metric is evidence of AI authorship.**
2. **Code style is not provenance.**
3. Static analysis may describe complexity, structure, testing, or potentially risky behavior; it does not establish who or what wrote the code.
4. Known provenance supplied by the developer takes priority over classifier guesses.
5. AI assistance is not treated as a defect.
6. Poorly reviewed code can be human-written; carefully reviewed code can be AI-assisted.
7. Results should be reported as measurements and comparisons, not accusations.
8. Ambiguous results stay ambiguous.

---

## What we hope to learn

The strongest possible outcome is not a detector that claims to know who wrote a file.

It is a reproducible answer to questions such as:

- Which static metrics are stable enough to compare across projects?
- Which apparent "AI-code" signals disappear when tested against known provenance?
- Are any differences better explained by review/testing practices than by AI use?
- Can we measure careless shipping practices without pretending that code style reveals authorship?
- How much uncertainty remains after static analysis?

If the analysis cannot reliably distinguish development provenance, that is a valid and important research result.

Thanks for helping us test it.
