from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone

TRANSLATION_RE = re.compile(
    r"\b(ai[- ]?(?:translated|translation|translations)|"
    r"(?:translated|translation|translations).{0,35}\b(?:ai|chatgpt|claude|gpt|llm)\b)\b",
    re.I | re.S,
)

AUDIO_RE = re.compile(
    r"\b(ai[- ]?(?:generated[- ]?)?(?:music|song|songs|voice|voices|audio)|"
    r"(?:music|song|songs|voice|voices|audio).{0,35}"
    r"\b(?:ai|chatgpt|claude|gpt|llm)\b)\b",
    re.I | re.S,
)

ASSET_RE = re.compile(
    r"\bai[- ]?(?:generated[- ]?)?(?:art|artwork|image|images|texture|textures|icon|icons|"
    r"thumbnail|thumbnails|illustration|illustrations|face|faces|cover image|cover art)\b"
    r"|\b(?:art|artwork|image|images|texture|textures|icon|icons|thumbnail|thumbnails|"
    r"illustration|illustrations|face|faces|cover image|cover art)\b.{0,35}"
    r"\b(?:ai|chatgpt|claude|gpt|llm)\b",
    re.I | re.S,
)

NAMED_TOOL_RE = re.compile(
    r"\b(chat\s*gpt|chatgpt|gpt(?:[-\s]?(?:3(?:\.5)?|4(?:o)?|5))?|claude|"
    r"(?:github\s+)?copilot|gemini|llms?|large language models?|"
    r"cursor\s+(?:ai|ide|editor))\b",
    re.I,
)

GENERIC_AI_RE = re.compile(
    r"\b(?:generative\s+ai|genai|artificial intelligence|ai)\b",
    re.I,
)

CODE_RE = re.compile(
    r"\b(code|coded|coding|script|scripts|lua|program|programming|implementation|"
    r"implemented|function|functions|debug|debugging|refactor|refactoring|source code)\b",
    re.I,
)

USE_RE = re.compile(
    r"\b(using|used|with|via|assisted|helped|generated|wrote|written|coded|built|"
    r"developed|prompted|pair[- ]programming|created|made|debugged|refactored)\b",
    re.I,
)

GENERAL_DEVELOPMENT_RE = re.compile(
    r"\b(?:ai|artificial intelligence|generative ai|genai)\b"
    r".{0,70}\b(?:used|services?|assisted|helped)\b"
    r".{0,70}\b(?:during|for|in)\b"
    r".{0,30}\b(?:development|developing)\b"
    r"|\b(?:used|using)\b.{0,40}\b(?:ai|artificial intelligence|generative ai|genai)\b"
    r".{0,70}\b(?:during|for|in)\b.{0,30}\b(?:development|developing)\b",
    re.I | re.S,
)

VIBE_RE = re.compile(r"\bvibe[-\s]?cod(?:e|ed|ing)\b", re.I)

# We intentionally use a fairly tight local window. The previous extractor
# matched "AI faction mod" near the top of a huge description with "code"
# hundreds/thousands of characters later.
LOCAL_RADIUS = 180


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _snippet(text: str, start: int, end: int, radius: int = 150) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def _local_window(text: str, match: re.Match[str], radius: int = LOCAL_RADIUS) -> tuple[str, int, int]:
    left = max(0, match.start() - radius)
    right = min(len(text), match.end() + radius)
    return text[left:right], left, right


def _find_code_claim(text: str) -> tuple[str, str, str] | None:
    """
    Return (evidence_type, classification, snippet) only when AI/tool use and
    coding language occur in the same local context.
    """
    vibe = VIBE_RE.search(text)
    if vibe:
        return (
            "code",
            "explicit_vibe_coding_claim",
            _snippet(text, vibe.start(), vibe.end()),
        )

    # Named tools are the strongest signal. Require code context AND a use verb
    # within +/- LOCAL_RADIUS of the actual tool mention.
    for tool in NAMED_TOOL_RE.finditer(text):
        window, left, _ = _local_window(text, tool)
        code = CODE_RE.search(window)
        use = USE_RE.search(window)

        if code and use:
            start = left + min(tool.start() - left, code.start(), use.start())
            end = left + max(tool.end() - left, code.end(), use.end())
            return (
                "code",
                "named_tool_code_claim",
                _snippet(text, start, end),
            )

    # Generic "AI" is much noisier. Require both code language and an explicit
    # use/action verb in the same tight window.
    for ai in GENERIC_AI_RE.finditer(text):
        window, left, _ = _local_window(text, ai)
        code = CODE_RE.search(window)
        use = USE_RE.search(window)

        if code and use:
            start = left + min(ai.start() - left, code.start(), use.start())
            end = left + max(ai.end() - left, code.end(), use.end())
            return (
                "code",
                "generic_ai_code_claim",
                _snippet(text, start, end),
            )

    # "AI services used during development" is real provenance evidence, but it
    # does not establish code generation or coding assistance.
    general = GENERAL_DEVELOPMENT_RE.search(text)
    if general:
        return (
            "development_general",
            "ai_development_scope_unspecified",
            _snippet(text, general.start(), general.end()),
        )

    return None


def _domain_evidence(text: str) -> tuple[str, str, str] | None:
    # Specific non-code provenance wins before generic development analysis.
    match = TRANSLATION_RE.search(text)
    if match:
        return (
            "translation",
            "ai_translation_claim",
            _snippet(text, match.start(), match.end()),
        )

    match = ASSET_RE.search(text)
    if match:
        return (
            "assets",
            "ai_asset_claim",
            _snippet(text, match.start(), match.end()),
        )

    match = AUDIO_RE.search(text)
    if match:
        return (
            "audio",
            "ai_audio_claim",
            _snippet(text, match.start(), match.end()),
        )

    return _find_code_claim(text)


# These are screening labels; evidence_type/classification are the provenance
# model consumed by review. A mention alone never establishes tool use.
DOMAIN_LABELS = {
    'named_tool_code_claim': 'explicit_genai_dev',
    'generic_ai_code_claim': 'explicit_ai_dev_unspecified',
    'explicit_vibe_coding_claim': 'explicit_vibe_coding',
    'ai_development_scope_unspecified': 'explicit_ai_dev_unspecified',
    'ai_asset_claim': 'ai_art_or_asset_mention',
    'ai_translation_claim': 'ai_translation_claim',
    'ai_audio_claim': 'ai_audio_claim',
}
POLICY_RE = re.compile(r"\b(?:don['’]?t|do not|never|no|without|against|forbid|banned)\b.{0,60}\b(?:ai|chatgpt|claude|copilot|generative)\b", re.I)
GAMEPLAY_RE = re.compile(r'\b(?:pathfinding|npc|npcs|zombie|zombies|survivor|faction|enemy|enemies|behavior|behaviour)\b', re.I)
TOOL_NAMES = [(re.compile(pattern, re.I), name) for pattern, name in [
    (r'\bchat\s*gpt\b', 'ChatGPT'), (r'\bgpt(?:[-\s]?(?:3(?:\.5)?|4o?|5))?\b', 'GPT'),
    (r'\bclaude\b', 'Claude'), (r'\b(?:github\s+)?copilot\b', 'Copilot'),
    (r'\bgemini\b', 'Gemini'), (r'\bcursor\s+(?:ai|ide|editor)\b', 'Cursor'),
    (r'\b(?:llms?|large language models?)\b', 'LLM'),
]]


def classify_ai_mention(title: str | None, description: str | None):
    text = _clean(f'{title or ""} {description or ""}')
    mention = NAMED_TOOL_RE.search(text) or GENERIC_AI_RE.search(text) or VIBE_RE.search(text)
    if not mention:
        return None
    tools = sorted({name for pattern, name in TOOL_NAMES if pattern.search(text)})
    # Analyze local sentences independently so rejection/gameplay text cannot
    # combine with unrelated coding prose to create a development claim.
    domains = []
    policy = gameplay = False
    for sentence in re.split(r'(?<=[.!?])\s+|[\r\n]+', text):
        if POLICY_RE.search(sentence):
            policy = True
            continue
        if GAMEPLAY_RE.search(sentence) and GENERIC_AI_RE.search(sentence) and not NAMED_TOOL_RE.search(sentence):
            gameplay = True
            # Explicit generative asset/translation/audio evidence still counts.
            if not any(p.search(sentence) for p in (TRANSLATION_RE, ASSET_RE, AUDIO_RE)):
                continue
        domain = _domain_evidence(sentence)
        if domain:
            domains.append(domain)
    if domains:
        # Preserve the existing one-candidate-per-item precedence.
        priority = {'translation': 0, 'assets': 1, 'audio': 2, 'code': 3, 'development_general': 4}
        evidence_type, classification, snippet = min(domains, key=lambda d: priority[d[0]])
        return dict(classification=DOMAIN_LABELS[classification], tools=tools,
                    evidence_type=evidence_type, provenance_classification=classification, snippet=snippet)
    label = ('ai_policy_or_rejection' if policy else 'gameplay_ai' if gameplay else
             'tool_mention_unclear' if tools else 'generic_ai_unclear')
    return dict(classification=label, tools=tools, evidence_type=None,
                provenance_classification=None, snippet=_snippet(text, mention.start(), mention.end()))


def _date(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d') if timestamp is not None else '?'


def overview(conn: sqlite3.Connection):
    row = conn.execute("""SELECT COUNT(*), COUNT(DISTINCT NULLIF(creator_steam_id, '')),
        MIN(time_created), MAX(time_created),
        COALESCE(SUM(trim(COALESCE(title,'')) = ''),0),
        COALESCE(SUM(trim(COALESCE(description,'')) = ''),0) FROM mods""").fetchone()
    return dict(items=row[0], authors=row[1], oldest=_date(row[2]), newest=_date(row[3]),
                missing_titles=row[4], missing_descriptions=row[5])


def timeline(conn: sqlite3.Connection):
    return [tuple(row) for row in conn.execute("""SELECT strftime('%Y', time_created, 'unixepoch') AS year,
        COUNT(*) FROM mods WHERE time_created IS NOT NULL GROUP BY year ORDER BY year""")]


def top_authors(conn: sqlite3.Connection, limit: int = 25):
    return [tuple(row) for row in conn.execute("""SELECT creator_steam_id, COUNT(*) AS n FROM mods
        WHERE COALESCE(creator_steam_id,'') != '' GROUP BY creator_steam_id
        ORDER BY n DESC, creator_steam_id LIMIT ?""", (max(0, limit),))]


def top_tags(conn: sqlite3.Connection, limit: int = 30):
    counts = Counter()
    for row in conn.execute('SELECT tags_json FROM mods'):
        counts.update(set(json.loads(row[0] or '[]')))
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:max(0, limit)]


def ai_mentions(conn: sqlite3.Connection, limit: int = 50, *, progress: bool = True):
    """Read-only scan. Limit bounds examples, never summary counts."""
    summary = Counter()
    matches = []
    candidates = 0
    for row in conn.execute('SELECT * FROM mods ORDER BY workshop_id'):
        result = classify_ai_mention(row['title'], row['description'])
        if result is None:
            continue
        candidates += 1
        summary[result['classification']] += 1
        if len(matches) < max(0, limit):
            matches.append(dict(result, workshop_id=row['workshop_id'], title=row['title'],
                                created=_date(row['time_created']),
                                updated=_date(row['time_updated']) if 'time_updated' in row.keys() else '?'))
    return summary, matches, candidates
