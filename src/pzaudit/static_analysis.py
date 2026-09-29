from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

SCHEMA_VERSION = 1
DEFAULT_MAX_FILE_BYTES = 2_000_000

SOURCE_LANGUAGES = {
    ".lua": "Lua",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
}

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "dist",
    "build",
    "vendor",
    "third_party",
}

TEST_DIR_NAMES = {"test", "tests", "spec", "specs", "__tests__"}
TEST_FILE_RE = re.compile(
    r"(^test_.+|.+_test|.+\.test|.+\.spec)\.(?:lua|py|js|jsx|mjs|cjs|ts|tsx|java|c|cc|cpp|cxx|cs|go|rs|rb|php)$",
    re.I,
)

LINT_CONFIG_NAMES = {
    ".flake8",
    "ruff.toml",
    ".ruff.toml",
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    "eslint.config.js",
    "eslint.config.mjs",
    ".luacheckrc",
    "luacheckrc",
    "stylua.toml",
}
TYPECHECK_CONFIG_NAMES = {
    "mypy.ini",
    ".mypy.ini",
    "pyrightconfig.json",
    "tsconfig.json",
}
TEST_CONFIG_NAMES = {
    "pytest.ini",
    "tox.ini",
    "jest.config.js",
    "jest.config.ts",
    "vitest.config.js",
    "vitest.config.ts",
}

CAPABILITY_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "process_execution": {
        ".py": (r"\bsubprocess\.", r"\bos\.system\s*\(", r"\bos\.popen\s*\("),
        ".lua": (r"\bos\.execute\s*\(", r"\bio\.popen\s*\("),
        ".js": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".jsx": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".mjs": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".cjs": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".ts": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".tsx": (r"\bchild_process\b", r"\bexec(?:File)?(?:Sync)?\s*\(", r"\bspawn(?:Sync)?\s*\("),
        ".sh": (r"\beval\b", r"\b(?:bash|sh|zsh)\s+-c\b"),
    },
    "dynamic_code_loading": {
        ".py": (r"\beval\s*\(", r"\bexec\s*\(", r"\bcompile\s*\("),
        ".lua": (r"\bloadstring\s*\(", r"\bload\s*\(", r"\bdofile\s*\("),
        ".js": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
        ".jsx": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
        ".mjs": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
        ".cjs": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
        ".ts": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
        ".tsx": (r"\beval\s*\(", r"\bnew\s+Function\s*\("),
    },
    "filesystem_io": {
        ".py": (r"\bopen\s*\(", r"\bpathlib\.", r"\bPath\s*\("),
        ".lua": (
            r"\bio\.(?:open|input|output|lines)\s*\(",
            r"\bgetFile(?:Reader|Writer)\s*\(",
        ),
        ".js": (r"\bfs\.", r"\bnode:fs\b"),
        ".jsx": (r"\bfs\.", r"\bnode:fs\b"),
        ".mjs": (r"\bfs\.", r"\bnode:fs\b"),
        ".cjs": (r"\bfs\.", r"\bnode:fs\b"),
        ".ts": (r"\bfs\.", r"\bnode:fs\b"),
        ".tsx": (r"\bfs\.", r"\bnode:fs\b"),
    },
    "network_io": {
        ".py": (
            r"\brequests\.",
            r"\bhttpx\.",
            r"\burllib\.",
            r"\bsocket\.",
            r"\baiohttp\.",
        ),
        ".lua": (r"\bsocket\.", r"\bhttp\.(?:request|get)\s*\("),
        ".js": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
        ".jsx": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
        ".mjs": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
        ".cjs": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
        ".ts": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
        ".tsx": (r"\bfetch\s*\(", r"\baxios\.", r"\b(?:http|https)\.request\s*\("),
    },
}


def _is_test_file(relative: Path) -> bool:
    parts = {part.lower() for part in relative.parts[:-1]}
    return bool(parts & TEST_DIR_NAMES) or bool(TEST_FILE_RE.match(relative.name))


def _is_ci_file(relative: Path) -> bool:
    posix = relative.as_posix().lower()
    name = relative.name.lower()
    return (
        posix.startswith(".github/workflows/")
        or posix == ".circleci/config.yml"
        or name in {"jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"}
    )


def _strip_comments(text: str, extension: str) -> str:
    if extension == ".lua":
        text = re.sub(r"--\[\[.*?\]\]", " ", text, flags=re.S)
        return re.sub(r"--[^\n]*", " ", text)

    if extension in {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".java",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".php",
    }:
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        return re.sub(r"//[^\n]*", " ", text)

    if extension in {".py", ".rb", ".sh"}:
        return re.sub(r"(?m)^\s*#.*$", " ", text)

    return text


def _line_metrics(text: str, extension: str) -> dict[str, int]:
    total = blank = comments = 0
    in_block = False

    for line in text.splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blank += 1
            continue

        if extension == ".lua":
            if in_block:
                comments += 1
                if "]]" in stripped:
                    in_block = False
                continue
            if stripped.startswith("--[["):
                comments += 1
                if "]]" not in stripped[4:]:
                    in_block = True
                continue
            if stripped.startswith("--"):
                comments += 1
                continue

        elif extension in {
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".java",
            ".c",
            ".h",
            ".cc",
            ".cpp",
            ".cxx",
            ".hpp",
            ".cs",
            ".go",
            ".rs",
            ".php",
        }:
            if in_block:
                comments += 1
                if "*/" in stripped:
                    in_block = False
                continue
            if stripped.startswith("/*"):
                comments += 1
                if "*/" not in stripped[2:]:
                    in_block = True
                continue
            if stripped.startswith("//"):
                comments += 1
                continue

        elif extension in {".py", ".rb", ".sh"} and stripped.startswith("#"):
            comments += 1
            continue

    code = max(0, total - blank - comments)
    return {
        "total": total,
        "code": code,
        "blank": blank,
        "comment": comments,
    }


def _python_structure(text: str) -> dict[str, int]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            "functions": 0,
            "classes": 0,
            "branch_points": 0,
            "parse_errors": 1,
        }

    functions = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(tree)
    )
    classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    branch_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.BoolOp,
        ast.IfExp,
        ast.Match,
    )
    branch_points = sum(isinstance(node, branch_types) for node in ast.walk(tree))
    return {
        "functions": functions,
        "classes": classes,
        "branch_points": branch_points,
        "parse_errors": 0,
    }


def _heuristic_structure(text: str, extension: str) -> dict[str, int]:
    clean = _strip_comments(text, extension)

    if extension == ".lua":
        functions = len(re.findall(r"\bfunction\b", clean))
        branches = len(
            re.findall(r"\b(?:if|elseif|for|while|repeat)\b", clean)
        )
        return {
            "functions": functions,
            "classes": 0,
            "branch_points": branches,
            "parse_errors": 0,
        }

    if extension in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        functions = len(re.findall(r"\bfunction\b|=>", clean))
        branches = len(
            re.findall(r"\b(?:if|for|while|case|catch)\b|\?", clean)
        )
        classes = len(re.findall(r"\bclass\s+[A-Za-z_$]", clean))
        return {
            "functions": functions,
            "classes": classes,
            "branch_points": branches,
            "parse_errors": 0,
        }

    if extension in {".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".go", ".rs"}:
        functions = len(
            re.findall(
                r"(?m)^[^\n;{}]*(?:\)|\bfn\s+\w+|\bfunc\s+\w+)\s*(?:->[^\{]+)?\{",
                clean,
            )
        )
        branches = len(
            re.findall(r"\b(?:if|for|while|case|catch|match)\b", clean)
        )
        classes = len(
            re.findall(r"\b(?:class|struct|interface|enum)\s+\w+", clean)
        )
        return {
            "functions": functions,
            "classes": classes,
            "branch_points": branches,
            "parse_errors": 0,
        }

    return {
        "functions": 0,
        "classes": 0,
        "branch_points": 0,
        "parse_errors": 0,
    }


def _structure_metrics(text: str, extension: str) -> dict[str, int]:
    if extension == ".py":
        return _python_structure(text)
    return _heuristic_structure(text, extension)


def _capability_counts(text: str, extension: str) -> dict[str, int]:
    clean = _strip_comments(text, extension)
    result: dict[str, int] = {}

    for category, per_extension in CAPABILITY_PATTERNS.items():
        patterns = per_extension.get(extension, ())
        count = sum(
            len(re.findall(pattern, clean, flags=re.I))
            for pattern in patterns
        )
        if count:
            result[category] = count

    return result


def _read_source(path: Path, max_file_bytes: int) -> tuple[str | None, str | None, bytes | None]:
    try:
        size = path.stat().st_size
    except OSError:
        return None, "unreadable", None

    if size > max_file_bytes:
        return None, "too_large", None

    try:
        raw = path.read_bytes()
    except OSError:
        return None, "unreadable", None

    if b"\x00" in raw:
        return None, "binary", raw

    try:
        return raw.decode("utf-8"), None, raw
    except UnicodeDecodeError:
        return None, "non_utf8", raw


def _iter_project_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS
            and not (Path(dirpath) / name).is_symlink()
        ]

        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if path.is_symlink():
                continue
            yield path


def _development_signals(
    all_files: list[Path],
    root: Path,
    source_files: list[Path],
) -> dict[str, object]:
    relatives = [path.relative_to(root) for path in all_files]
    source_relatives = [path.relative_to(root) for path in source_files]

    lower_names = {relative.name.lower() for relative in relatives}
    test_files = [relative for relative in source_relatives if _is_test_file(relative)]
    ci_files = [relative for relative in relatives if _is_ci_file(relative)]

    has_readme = any(
        relative.name.lower().startswith("readme")
        for relative in relatives
        if len(relative.parts) == 1
    )
    has_docs_dir = any(
        relative.parts and relative.parts[0].lower() in {"docs", "documentation"}
        for relative in relatives
    )

    has_lint = bool(lower_names & LINT_CONFIG_NAMES)
    has_typecheck = bool(lower_names & TYPECHECK_CONFIG_NAMES)
    has_test_config = bool(lower_names & TEST_CONFIG_NAMES)

    pyproject = root / "pyproject.toml"
    if pyproject.exists() and pyproject.is_file():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            pyproject_text = ""
        has_lint = has_lint or any(
            marker in pyproject_text
            for marker in ("[tool.ruff", "[tool.black", "[tool.isort")
        )
        has_typecheck = has_typecheck or "[tool.mypy" in pyproject_text
        has_test_config = has_test_config or "[tool.pytest" in pyproject_text

    return {
        "test_files": len(test_files),
        "has_tests": bool(test_files),
        "ci_files": len(ci_files),
        "has_ci": bool(ci_files),
        "has_lint_config": has_lint,
        "has_typecheck_config": has_typecheck,
        "has_test_config": has_test_config,
        "has_readme": has_readme,
        "has_docs_directory": has_docs_dir,
    }


def analyze_project(
    root: Path | str,
    *,
    include_file_metrics: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, object]:
    root = Path(root).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"project path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    if max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be greater than zero")

    all_files = list(_iter_project_files(root))
    source_candidates = [
        path for path in all_files if path.suffix.lower() in SOURCE_LANGUAGES
    ]

    language_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    line_totals: Counter[str] = Counter()
    structure_totals: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    capability_occurrences: Counter[str] = Counter()
    capability_files: defaultdict[str, set[str]] = defaultdict(set)
    file_metrics: list[dict[str, object]] = []
    source_bytes = 0
    analyzed_source_files: list[Path] = []
    fingerprint = hashlib.sha256()

    for path in source_candidates:
        extension = path.suffix.lower()
        relative = path.relative_to(root)
        text, skip_reason, raw = _read_source(path, max_file_bytes)

        if skip_reason:
            skipped[skip_reason] += 1
            continue

        assert text is not None
        assert raw is not None

        analyzed_source_files.append(path)
        source_bytes += len(raw)
        language_counts[SOURCE_LANGUAGES[extension]] += 1
        extension_counts[extension] += 1

        fingerprint.update(relative.as_posix().encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(hashlib.sha256(raw).digest())

        lines = _line_metrics(text, extension)
        structure = _structure_metrics(text, extension)
        capabilities = _capability_counts(text, extension)

        line_totals.update(lines)
        structure_totals.update(structure)

        for category, count in capabilities.items():
            capability_occurrences[category] += count
            capability_files[category].add(relative.as_posix())

        if include_file_metrics:
            file_metrics.append(
                {
                    "path": relative.as_posix(),
                    "language": SOURCE_LANGUAGES[extension],
                    "bytes": len(raw),
                    "lines": lines,
                    "structure": structure,
                    "capability_signals": capabilities,
                    "is_test_file": _is_test_file(relative),
                }
            )

    capability_report = {
        category: {
            "occurrences": capability_occurrences.get(category, 0),
            "files": len(capability_files.get(category, set())),
        }
        for category in CAPABILITY_PATTERNS
    }

    code_lines = line_totals.get("code", 0)
    branch_points = structure_totals.get("branch_points", 0)
    branch_points_per_kloc = (
        round(branch_points / code_lines * 1000, 3)
        if code_lines
        else 0.0
    )

    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": "pzaudit",
            "version": __version__,
            "analysis": "static-project-summary",
        },
        "project": {
            "name": root.name,
            "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_fingerprint_sha256": (
                fingerprint.hexdigest() if analyzed_source_files else None
            ),
            "privacy": (
                "aggregate-only"
                if not include_file_metrics
                else "includes-relative-file-metrics"
            ),
        },
        "analysis_scope": {
            "source_extensions": sorted(SOURCE_LANGUAGES),
            "excluded_directories": sorted(EXCLUDED_DIRS),
            "max_file_bytes": max_file_bytes,
            "symlinks_followed": False,
        },
        "inventory": {
            "project_files_seen": len(all_files),
            "source_candidates": len(source_candidates),
            "source_files_analyzed": len(analyzed_source_files),
            "source_bytes_analyzed": source_bytes,
            "source_files_by_language": dict(sorted(language_counts.items())),
            "source_files_by_extension": dict(sorted(extension_counts.items())),
            "skipped_source_files": dict(sorted(skipped.items())),
        },
        "metrics": {
            "lines": {
                "total": line_totals.get("total", 0),
                "code": code_lines,
                "blank": line_totals.get("blank", 0),
                "comment": line_totals.get("comment", 0),
            },
            "structure": {
                "functions": structure_totals.get("functions", 0),
                "classes_or_structs": structure_totals.get("classes", 0),
                "branch_points": branch_points,
                "branch_points_per_kloc": branch_points_per_kloc,
                "parse_errors": structure_totals.get("parse_errors", 0),
            },
        },
        "development_signals": _development_signals(
            all_files,
            root,
            analyzed_source_files,
        ),
        "capability_signals": capability_report,
        "interpretation": {
            "ai_authorship_score": None,
            "notes": [
                "No metric in this report establishes AI authorship.",
                "Capability signals identify API categories for review; they do not imply maliciousness or poor quality.",
                "Non-Python structure metrics are heuristic and should not be treated as exact cyclomatic complexity.",
                "Known developer provenance should be compared against these measurements rather than replaced by them.",
            ],
        },
    }

    if include_file_metrics:
        report["files"] = sorted(
            file_metrics,
            key=lambda item: str(item["path"]),
        )

    return report


def write_report(report: dict[str, object], output: Path | str) -> Path:
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output
