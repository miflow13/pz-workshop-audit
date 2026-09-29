import json
from pathlib import Path

from pzaudit.cli import build_parser
from pzaudit.static_analysis import analyze_project, write_report


def test_analyze_project_aggregate_report_is_private_by_default(tmp_path: Path):
    (tmp_path / "media" / "lua").mkdir(parents=True)
    (tmp_path / "media" / "lua" / "main.lua").write_text(
        """-- comment
local function greet(name)
    if name then
        os.execute("echo hello")
        return "hi"
    end
end
""",
        encoding="utf-8",
    )

    (tmp_path / "helper.py").write_text(
        """def choose(value):
    if value:
        return 1
    return 0
""",
        encoding="utf-8",
    )

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_behavior.lua").write_text(
        """function test_behavior()
    return true
end
""",
        encoding="utf-8",
    )

    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text(
        "eval('ignored')",
        encoding="utf-8",
    )

    report = analyze_project(tmp_path)

    assert report["project"]["privacy"] == "aggregate-only"
    assert report["inventory"]["source_files_analyzed"] == 3
    assert report["inventory"]["source_files_by_language"] == {
        "Lua": 2,
        "Python": 1,
    }
    assert report["development_signals"]["has_tests"] is True
    assert report["development_signals"]["test_files"] == 1
    assert report["capability_signals"]["process_execution"]["occurrences"] == 1
    assert report["capability_signals"]["process_execution"]["files"] == 1
    assert report["capability_signals"]["dynamic_code_loading"]["occurrences"] == 0
    assert report["metrics"]["structure"]["functions"] == 3
    assert report["metrics"]["structure"]["branch_points"] == 2
    assert "files" not in report

    payload = json.dumps(report)
    assert "echo hello" not in payload
    assert "ignored.js" not in payload


def test_analyze_project_can_include_relative_file_metrics(tmp_path: Path):
    (tmp_path / "main.lua").write_text(
        """function run()
    return 1
end
""",
        encoding="utf-8",
    )

    report = analyze_project(tmp_path, include_file_metrics=True)

    assert report["project"]["privacy"] == "includes-relative-file-metrics"
    assert report["files"][0]["path"] == "main.lua"
    assert report["files"][0]["language"] == "Lua"
    assert "source" not in report["files"][0]
    assert "content" not in report["files"][0]


def test_large_source_file_is_skipped(tmp_path: Path):
    (tmp_path / "large.lua").write_text("x" * 20, encoding="utf-8")

    report = analyze_project(tmp_path, max_file_bytes=10)

    assert report["inventory"]["source_candidates"] == 1
    assert report["inventory"]["source_files_analyzed"] == 0
    assert report["inventory"]["skipped_source_files"] == {"too_large": 1}


def test_development_configs_are_detected(tmp_path: Path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "test.yml").write_text(
        "name: test\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
""",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")

    report = analyze_project(tmp_path)
    signals = report["development_signals"]

    assert signals["has_ci"] is True
    assert signals["ci_files"] == 1
    assert signals["has_readme"] is True
    assert signals["has_lint_config"] is True
    assert signals["has_typecheck_config"] is True
    assert signals["has_test_config"] is True


def test_write_report_and_cli_parser(tmp_path: Path):
    (tmp_path / "main.lua").write_text("return true\n", encoding="utf-8")
    report = analyze_project(tmp_path)

    output = write_report(report, tmp_path / "out" / "report.json")
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert loaded["schema_version"] == 1
    assert loaded["inventory"]["source_files_analyzed"] == 1

    args = build_parser().parse_args(
        [
            "analyze",
            str(tmp_path),
            "--output",
            str(tmp_path / "report.json"),
            "--include-file-metrics",
        ]
    )
    assert args.command == "analyze"
    assert args.include_file_metrics is True
