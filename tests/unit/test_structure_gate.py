from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import check_structure

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_config(root: Path, exemptions: dict[str, object]) -> Path:
    path = root / "structural-exemptions.json"
    path.write_text(json.dumps({"version": 1, "exemptions": exemptions}), encoding="utf-8")
    return path


def _exemption(
    *,
    file_lines: int,
    function_lines: int,
    functions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "max_file_lines": file_lines,
        "max_function_lines": function_lines,
        "over_limit_functions": functions or [],
        "owner": "test-maintainers",
        "reason": "Focused fixture for the structural ratchet contract.",
        "expires": "2099-12-31",
    }


def _function_with_lines(line_count: int, name: str = "oversized") -> str:
    assert line_count >= 2
    return f"def {name}():\n" + "".join(f"    value_{i} = {i}\n" for i in range(line_count - 1))


def _function_baseline(name: str, line: int, lines: int) -> dict[str, object]:
    return {"name": name, "line": line, "lines": lines}


def test_clean_tree_passes_without_exemptions(tmp_path: Path) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    (package / "clean.py").write_text("def small():\n    return 1\n", encoding="utf-8")

    report = check_structure.check_repository(tmp_path, _write_config(tmp_path, {}))

    assert report.errors == ()
    assert report.files[0].largest_function_lines == 2


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# line\n" * 401, "file=401/400"),
        (_function_with_lines(81), "largest_function=81/80"),
    ],
)
def test_new_file_or_function_violation_fails(tmp_path: Path, source: str, expected: str) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    (package / "new_debt.py").write_text(source, encoding="utf-8")

    report = check_structure.check_repository(tmp_path, _write_config(tmp_path, {}))

    assert any("new structural violation" in error and expected in error for error in report.errors)


def test_multiline_decorator_counts_toward_function_span(tmp_path: Path) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    decorated = '@decorator(\n    "fixture",\n)\n' + _function_with_lines(80)
    (package / "decorated.py").write_text(decorated, encoding="utf-8")

    report = check_structure.check_repository(tmp_path, _write_config(tmp_path, {}))

    assert report.files[0].largest_function_lines == 83
    assert any("largest_function=83/80" in error for error in report.errors)


def test_exemption_rejects_growth_and_requires_immediate_downward_ratchet(
    tmp_path: Path,
) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    source_path = package / "legacy.py"
    source_path.write_text(_function_with_lines(82), encoding="utf-8")
    config = _write_config(
        tmp_path,
        {
            "boltrig/legacy.py": _exemption(
                file_lines=82,
                function_lines=82,
                functions=[_function_baseline("oversized", 1, 82)],
            ),
        },
    )
    assert check_structure.check_repository(tmp_path, config).errors == ()

    source_path.write_text(_function_with_lines(83), encoding="utf-8")
    errors = check_structure.check_repository(tmp_path, config).errors
    assert any(error.startswith("file growth:") for error in errors)
    assert any(error.startswith("function growth:") for error in errors)

    source_path.write_text(_function_with_lines(81), encoding="utf-8")
    errors = check_structure.check_repository(tmp_path, config).errors
    assert any("file baseline is stale-high" in error for error in errors)
    assert any("function baseline is stale-high" in error for error in errors)


def test_new_over_limit_sibling_fails_below_existing_largest_function(
    tmp_path: Path,
) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    source_path = package / "legacy.py"
    source_path.write_text(
        _function_with_lines(90, "legacy") + "# padding\n" * 81,
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        {
            "boltrig/legacy.py": _exemption(
                file_lines=171,
                function_lines=90,
                functions=[_function_baseline("legacy", 1, 90)],
            )
        },
    )
    assert check_structure.check_repository(tmp_path, config).errors == ()

    source_path.write_text(
        _function_with_lines(90, "legacy") + _function_with_lines(81, "new_debt"),
        encoding="utf-8",
    )
    errors = check_structure.check_repository(tmp_path, config).errors

    assert any("new over-limit function" in error and "new_debt:91" in error for error in errors)


@pytest.mark.parametrize(
    "entry",
    [
        {**_exemption(file_lines=401, function_lines=0), "unexpected": True},
        {**_exemption(file_lines=401, function_lines=0), "owner": ""},
        {**_exemption(file_lines=401, function_lines=0), "expires": "2020-01-01"},
        _exemption(file_lines=400, function_lines=80),
    ],
)
def test_malformed_or_expired_exemption_fails(tmp_path: Path, entry: dict[str, object]) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    (package / "legacy.py").write_text("# line\n" * 401, encoding="utf-8")
    config = _write_config(tmp_path, {"boltrig/legacy.py": entry})

    report = check_structure.check_repository(tmp_path, config, today=date(2026, 7, 10))

    assert report.errors


def test_missing_and_stale_exemption_paths_fail(tmp_path: Path) -> None:
    package = tmp_path / "boltrig"
    package.mkdir()
    (package / "clean.py").write_text("value = 1\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        {
            "boltrig/clean.py": _exemption(file_lines=401, function_lines=0),
            "boltrig/missing.py": _exemption(file_lines=401, function_lines=0),
        },
    )

    errors = check_structure.check_repository(tmp_path, config).errors

    assert "stale exemption for clean file: boltrig/clean.py" in errors
    assert "exemption points to a missing or out-of-scope file: boltrig/missing.py" in errors


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "boltrig").mkdir()
    config = tmp_path / "structural-exemptions.json"
    config.write_text('{"version": 1, "version": 1, "exemptions": {}}', encoding="utf-8")

    report = check_structure.check_repository(tmp_path, config)

    assert report.errors == ("duplicate JSON key: 'version'",)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_catalogue_version_requires_an_integer(tmp_path: Path, version: object) -> None:
    (tmp_path / "boltrig").mkdir()
    config = tmp_path / "structural-exemptions.json"
    config.write_text(json.dumps({"version": version, "exemptions": {}}), encoding="utf-8")

    report = check_structure.check_repository(tmp_path, config)

    assert any("unsupported exemption catalogue version" in error for error in report.errors)


@pytest.mark.invariant("NFR-MNT-01")
def test_repository_structure_ratchet_is_clean() -> None:
    report = check_structure.check_repository(REPO_ROOT)

    assert report.errors == (), "\n".join(report.errors)
