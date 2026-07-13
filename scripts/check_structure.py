#!/usr/bin/env python3
"""Enforce Boltrig's physical-size floor with expiring debt ratchets.

Only ``boltrig/**/*.py`` is scanned. Clean files may not exceed 400 physical
lines and functions/methods may not exceed an 80-line AST source span. Existing
debt must be listed in the JSON exemptions file. Its file, largest-function,
and individual over-limit-function measurements must exactly match the current
source, so an improvement lowers the ratchet in the same change and cannot
silently regrow later.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "docs/refactoring/structural-exemptions.json"
FILE_LINE_LIMIT = 400
FUNCTION_LINE_LIMIT = 80
CONFIG_VERSION = 1
_EXEMPTION_FIELDS = {
    "max_file_lines",
    "max_function_lines",
    "over_limit_functions",
    "owner",
    "reason",
    "expires",
}


class StructureError(ValueError):
    """The source tree or exemption catalogue cannot be checked safely."""


@dataclass(frozen=True)
class FunctionMetric:
    name: str
    line: int
    lines: int


@dataclass(frozen=True)
class FileMetric:
    path: str
    file_lines: int
    functions: tuple[FunctionMetric, ...]

    @property
    def largest_function(self) -> FunctionMetric | None:
        return max(self.functions, key=lambda item: item.lines, default=None)

    @property
    def largest_function_lines(self) -> int:
        largest = self.largest_function
        return largest.lines if largest is not None else 0


@dataclass(frozen=True)
class Exemption:
    max_file_lines: int
    max_function_lines: int
    over_limit_functions: tuple[FunctionMetric, ...]
    owner: str
    reason: str
    expires: date


@dataclass(frozen=True)
class Report:
    files: tuple[FileMetric, ...]
    exemptions: dict[str, Exemption]
    errors: tuple[str, ...]

    @property
    def function_count(self) -> int:
        return sum(len(item.functions) for item in self.files)


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.metrics: list[FunctionMetric] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
        end = node.end_lineno or node.lineno
        name = ".".join((*self.scope, node.name))
        self.metrics.append(FunctionMetric(name=name, line=node.lineno, lines=end - start + 1))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


def _scan_file(path: Path, repo_root: Path) -> FileMetric:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        relative = path.relative_to(repo_root).as_posix()
        raise StructureError(f"cannot parse {relative}: {exc}") from exc
    visitor = _FunctionVisitor()
    visitor.visit(tree)
    return FileMetric(
        path=path.relative_to(repo_root).as_posix(),
        file_lines=len(source.splitlines()),
        functions=tuple(visitor.metrics),
    )


def scan_tree(repo_root: Path) -> tuple[FileMetric, ...]:
    source_root = repo_root / "boltrig"
    if not source_root.is_dir():
        raise StructureError(f"missing Python source root: {source_root}")
    paths = (
        path
        for path in source_root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    return tuple(_scan_file(path, repo_root) for path in sorted(paths))


def _parse_function_baselines(path: str, raw: Any) -> tuple[FunctionMetric, ...]:
    if not isinstance(raw, list):
        raise StructureError(f"exemption {path} over_limit_functions must be a list")
    baselines: list[FunctionMetric] = []
    identities: set[tuple[str, int]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"name", "line", "lines"}:
            raise StructureError(f"exemption {path} function baseline {index} is malformed")
        name, line, lines = item["name"], item["line"], item["lines"]
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise StructureError(f"exemption {path} function baseline {index} has invalid name")
        if (
            isinstance(line, bool)
            or not isinstance(line, int)
            or line < 1
            or isinstance(lines, bool)
            or not isinstance(lines, int)
            or lines <= FUNCTION_LINE_LIMIT
        ):
            raise StructureError(f"exemption {path} function baseline {index} is invalid")
        identity = (name, line)
        if identity in identities:
            raise StructureError(f"exemption {path} repeats function baseline {name}:{line}")
        identities.add(identity)
        baselines.append(FunctionMetric(name=name, line=line, lines=lines))
    return tuple(sorted(baselines, key=lambda item: (item.line, item.name)))


def _parse_exemption(path: str, raw: Any, *, today: date) -> Exemption:
    pure_path = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or pure_path.is_absolute()
        or pure_path.as_posix() != path
        or ".." in pure_path.parts
        or len(pure_path.parts) < 2
        or pure_path.parts[0] != "boltrig"
        or pure_path.suffix != ".py"
    ):
        raise StructureError(f"invalid exemption path: {path!r}")
    if not isinstance(raw, dict):
        raise StructureError(f"exemption {path} must be an object")
    fields = set(raw)
    if fields != _EXEMPTION_FIELDS:
        missing = sorted(_EXEMPTION_FIELDS - fields)
        extra = sorted(fields - _EXEMPTION_FIELDS)
        raise StructureError(
            f"exemption {path} fields malformed (missing={missing}, extra={extra})"
        )
    file_max = raw["max_file_lines"]
    function_max = raw["max_function_lines"]
    if (
        isinstance(file_max, bool)
        or not isinstance(file_max, int)
        or file_max < 1
        or isinstance(function_max, bool)
        or not isinstance(function_max, int)
        or function_max < 0
    ):
        raise StructureError(f"exemption {path} baselines must be non-negative integers")
    if file_max <= FILE_LINE_LIMIT and function_max <= FUNCTION_LINE_LIMIT:
        raise StructureError(f"exemption {path} does not exempt an over-limit baseline")
    function_baselines = _parse_function_baselines(path, raw["over_limit_functions"])
    recorded_largest = max((item.lines for item in function_baselines), default=0)
    if function_max > FUNCTION_LINE_LIMIT and recorded_largest != function_max:
        raise StructureError(
            f"exemption {path} largest-function baseline disagrees with function records"
        )
    if function_max <= FUNCTION_LINE_LIMIT and function_baselines:
        raise StructureError(f"exemption {path} records function debt below the function limit")
    owner, reason = raw["owner"], raw["reason"]
    if not isinstance(owner, str) or not owner.strip() or owner != owner.strip():
        raise StructureError(f"exemption {path} must have a non-empty, trimmed owner")
    if not isinstance(reason, str) or not reason.strip() or reason != reason.strip():
        raise StructureError(f"exemption {path} must have a non-empty, trimmed reason")
    try:
        expires = date.fromisoformat(raw["expires"])
    except (TypeError, ValueError) as exc:
        raise StructureError(f"exemption {path} expires must be an ISO date") from exc
    if expires < today:
        raise StructureError(f"exemption {path} expired on {expires.isoformat()}")
    return Exemption(file_max, function_max, function_baselines, owner, reason, expires)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructureError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_exemptions(path: Path, *, today: date | None = None) -> dict[str, Exemption]:
    current_date = today or date.today()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StructureError(f"cannot load exemption catalogue {path}: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"version", "exemptions"}:
        raise StructureError("exemption catalogue must contain exactly version and exemptions")
    if type(raw["version"]) is not int or raw["version"] != CONFIG_VERSION:
        raise StructureError(f"unsupported exemption catalogue version: {raw['version']!r}")
    if not isinstance(raw["exemptions"], dict):
        raise StructureError("exemptions must be an object keyed by repository-relative path")
    return {
        item_path: _parse_exemption(item_path, item, today=current_date)
        for item_path, item in raw["exemptions"].items()
    }


def _compare_exact(label: str, path: str, measured: int, baseline: int) -> list[str]:
    if measured > baseline:
        return [f"{label} growth: {path} is {measured} lines; ratchet is {baseline}"]
    if measured < baseline:
        return [
            f"{label} baseline is stale-high: {path} is {measured} lines; "
            f"lower the ratchet from {baseline} in this change"
        ]
    return []


def _over_limit_functions(metric: FileMetric) -> tuple[FunctionMetric, ...]:
    return tuple(item for item in metric.functions if item.lines > FUNCTION_LINE_LIMIT)


def _evaluate_function_debt(metric: FileMetric, exemption: Exemption) -> list[str]:
    errors: list[str] = []
    current = {(item.name, item.line): item for item in _over_limit_functions(metric)}
    recorded = {(item.name, item.line): item for item in exemption.over_limit_functions}
    for identity in sorted(set(current) - set(recorded)):
        item = current[identity]
        errors.append(
            f"new over-limit function: {metric.path}:{item.name}:{item.line} "
            f"is {item.lines}/{FUNCTION_LINE_LIMIT} lines"
        )
    for identity in sorted(set(recorded) - set(current)):
        item = recorded[identity]
        errors.append(
            f"stale function baseline: {metric.path}:{item.name}:{item.line}; "
            "remove or update it in this change"
        )
    for identity in sorted(set(current) & set(recorded)):
        item, baseline = current[identity], recorded[identity]
        location = f"{metric.path}:{item.name}:{item.line}"
        errors.extend(_compare_exact("function", location, item.lines, baseline.lines))
    return errors


def _evaluate_exempted(metric: FileMetric, exemption: Exemption) -> list[str]:
    function_debt = _over_limit_functions(metric)
    if metric.file_lines <= FILE_LINE_LIMIT and not function_debt:
        return [f"stale exemption for clean file: {metric.path}"]
    errors = _compare_exact("file", metric.path, metric.file_lines, exemption.max_file_lines)
    errors.extend(
        _compare_exact(
            "largest-function",
            metric.path,
            metric.largest_function_lines,
            exemption.max_function_lines,
        )
    )
    errors.extend(_evaluate_function_debt(metric, exemption))
    return errors


def _evaluate_metrics(
    metrics: tuple[FileMetric, ...], exemptions: dict[str, Exemption]
) -> tuple[str, ...]:
    errors: list[str] = []
    by_path = {item.path: item for item in metrics}
    for path in sorted(set(exemptions) - set(by_path)):
        errors.append(f"exemption points to a missing or out-of-scope file: {path}")
    for metric in metrics:
        exemption = exemptions.get(metric.path)
        if exemption is not None:
            errors.extend(_evaluate_exempted(metric, exemption))
            continue
        if metric.file_lines > FILE_LINE_LIMIT or _over_limit_functions(metric):
            errors.append(
                f"new structural violation: {metric.path} "
                f"file={metric.file_lines}/{FILE_LINE_LIMIT}, "
                f"largest_function={metric.largest_function_lines}/{FUNCTION_LINE_LIMIT}"
            )
    return tuple(errors)


def check_repository(
    repo_root: Path = ROOT,
    config_path: Path | None = None,
    *,
    today: date | None = None,
) -> Report:
    resolved_root = repo_root.resolve()
    resolved_config = (config_path or resolved_root / DEFAULT_CONFIG.relative_to(ROOT)).resolve()
    try:
        exemptions = load_exemptions(resolved_config, today=today)
        files = scan_tree(resolved_root)
    except StructureError as exc:
        return Report(files=(), exemptions={}, errors=(str(exc),))
    return Report(files=files, exemptions=exemptions, errors=_evaluate_metrics(files, exemptions))


def _print_report(report: Report) -> None:
    print("Python structural ratchet")
    print(
        f"files={len(report.files)} functions={report.function_count} "
        f"limits=file:{FILE_LINE_LIMIT},function:{FUNCTION_LINE_LIMIT} "
        f"exemptions={len(report.exemptions)}"
    )
    if report.exemptions and report.files:
        by_path = {item.path: item for item in report.files}
        print("Existing debt (measured/baseline):")
        for path, exemption in sorted(report.exemptions.items()):
            metric = by_path.get(path)
            if metric is None:
                continue
            print(
                f"  {path}: file={metric.file_lines}/{exemption.max_file_lines}, "
                f"function={metric.largest_function_lines}/{exemption.max_function_lines}, "
                f"owner={exemption.owner}, expires={exemption.expires.isoformat()}"
            )
    if report.errors:
        sys.stdout.flush()
        print("FAIL:", file=sys.stderr)
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        return
    print("PASS: no new structural debt and every ratchet matches current source.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--config", type=Path, help="exemption JSON (defaults under root)")
    args = parser.parse_args(argv)
    report = check_repository(args.root, args.config)
    _print_report(report)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
