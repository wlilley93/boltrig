#!/usr/bin/env python3
"""Fail when Boltrig's generated VDS screen or route ledgers drift.

``vds ledger screens`` and ``vds ledger routes --from ...`` remain the
canonical generators.  The VDS binary is not a pinned repository dependency,
so the release gate checks the generated records with the pinned Python
environment instead of pretending a developer-local binary exists in CI.

This check deliberately makes no visual verdict.  It verifies source and
manifest ownership, digests, live JSX reference coordinates, and the existing
``captured_unreviewed`` / ``not_assessed`` evidence boundary only.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import posixpath
import re
import stat
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vds_ledger_support import (  # noqa: E402
    LedgerError,
    load_json,
    load_yaml,
    repo_path,
    require_digest,
    sha256,
    value_digest,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ".vds/config.toml"
ROUTE_SOURCE_PATH = "docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json"
MIN_SCREEN_FILES = 10
MIN_ROUTE_FILES = 6
DEFAULT_CAPTURE_SOURCE_SCOPE = (
    "apps/worker/src",
    "apps/worker/tests/visual",
)
SCREEN_KEYS = {
    "schema_version",
    "generated_at",
    "generated_by",
    "source_globs",
    "source_digest",
    "content_digest",
    "screens",
}
SCREEN_ROW_KEYS = {"route", "digest", "references"}
REFERENCE_KEYS = {
    "name",
    "root",
    "export_name",
    "namespace_member",
    "kind",
    "import_path",
    "resolved_path",
    "line",
    "unresolved_because",
}
ROUTE_KEYS = {
    "schemaVersion",
    "generatedBy",
    "takenAt",
    "source",
    "routes",
    "doesNotCover",
    "contentDigest",
}
_ROUTE_SOURCE_RE = re.compile(
    r"(?P<capture>[^ ]+capture-manifest\.json) \((?P<capture_digest>sha256:[0-9a-f]{64})\) "
    r"and metrics\.json \((?P<metrics_digest>sha256:[0-9a-f]{64})\)\Z"
)
_IMPORT_RE = re.compile(
    r"\bimport\s+(?P<bindings>[\s\S]*?)\s+from\s+[\"'](?P<module>[^\"']+)[\"']\s*;"
)


@dataclass(frozen=True)
class Report:
    screen_count: int
    reference_count: int
    route_count: int
    errors: tuple[str, ...]


def source_tree_digest(root: Path, scopes: tuple[str, ...]) -> str:
    """Reproduce capture-current.mjs' path/type/content source digest."""

    digest = hashlib.sha256()
    for scope in scopes:
        scope_path = repo_path(root, scope, "capture source scope")
        if not scope_path.is_dir() or scope_path.is_symlink():
            raise LedgerError(f"capture source scope is not a real directory: {scope!r}")
        paths: list[Path] = []
        pending = [scope_path]
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.as_posix())
            except OSError as exc:
                raise LedgerError(f"cannot scan capture source scope {scope!r}: {exc}") from exc
            for path in entries:
                if (
                    path.name == ".DS_Store"
                    or path.name == "__pycache__"
                    or path.name.endswith(".pyc")
                ):
                    continue
                try:
                    mode = path.lstat().st_mode
                except OSError as exc:
                    raise LedgerError(f"cannot inspect capture source path {path}: {exc}") from exc
                if stat.S_ISDIR(mode):
                    pending.append(path)
                elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                    paths.append(path)
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
            relative_path = path.relative_to(root).as_posix()
            digest.update(relative_path.encode())
            digest.update(b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0")
                try:
                    digest.update(os.readlink(path).encode())
                except OSError as exc:
                    raise LedgerError(f"cannot read capture source symlink {path}: {exc}") from exc
                digest.update(b"\0")
            else:
                digest.update(b"file\0")
                try:
                    digest.update(path.read_bytes())
                except OSError as exc:
                    raise LedgerError(f"cannot read capture source file {path}: {exc}") from exc
                digest.update(b"\0")
    return digest.hexdigest()


def _screen_files(root: Path, globs: object) -> list[Path]:
    if not isinstance(globs, list) or not globs or not all(isinstance(item, str) for item in globs):
        raise LedgerError("[surface] screen_globs must be a non-empty string list")
    found: set[Path] = set()
    for pattern in globs:
        pure = PurePosixPath(pattern)
        if pure.is_absolute() or ".." in pure.parts or "\\" in pattern:
            raise LedgerError(f"unsafe screen glob: {pattern!r}")
        for raw_path in glob.glob(str(root / pattern), recursive=False):
            path = Path(raw_path)
            if path.is_file():
                repo_path(root, path.relative_to(root).as_posix(), "matched screen")
                found.add(path)
    files = sorted(found)
    if len(files) < MIN_SCREEN_FILES:
        raise LedgerError(
            f"screen scan found {len(files)} files; expected at least {MIN_SCREEN_FILES}"
        )
    return files


def _import_bindings(source: str) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {}
    for match in _IMPORT_RE.finditer(source):
        clause = re.sub(r"\btype\s+", "", match.group("bindings"))
        module = match.group("module")
        names: set[str] = set()
        default = clause.split(",", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", default):
            names.add(default)
        namespace = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
        if namespace:
            names.add(namespace.group(1))
        named = re.search(r"\{([\s\S]*?)\}", clause)
        if named:
            for item in named.group(1).split(","):
                words = re.findall(r"[A-Za-z_$][\w$]*", item)
                if words:
                    names.add(words[-1] if len(words) >= 3 and words[-2] == "as" else words[0])
        for name in names:
            bindings.setdefault(name, []).append(module)
    return bindings


def _has_local_definition(source: str, name: str) -> bool:
    escaped = re.escape(name)
    return bool(
        re.search(rf"\b(?:function|class)\s+{escaped}\b", source)
        or re.search(rf"\b(?:const|let|var)\s+{escaped}\s*(?::[^=]+)?=", source)
    )


def _validate_reference(
    root: Path,
    route: str,
    source: str,
    lines: list[str],
    imports: dict[str, list[str]],
    extensions: tuple[str, ...],
    reference: object,
) -> list[str]:
    if not isinstance(reference, dict):
        return [f"{route}: reference is not an object"]
    unknown = set(reference) - REFERENCE_KEYS
    required = REFERENCE_KEYS - {"resolved_path", "unresolved_because"}
    missing = required - set(reference)
    if unknown or missing:
        return [
            f"{route}: malformed reference keys (missing={sorted(missing)}, extra={sorted(unknown)})"
        ]
    name, component_root = reference.get("name"), reference.get("root")
    line = reference.get("line")
    kind, import_path = reference.get("kind"), reference.get("import_path")
    errors: list[str] = []
    if not isinstance(name, str) or not name or not isinstance(component_root, str):
        return [f"{route}: reference has an invalid name/root"]
    if type(line) is not int or line < 1 or line > len(lines):
        return [f"{route}: {name} points outside the file at line {line!r}"]
    if f"<{name}" not in lines[line - 1]:
        errors.append(f"{route}: {name} is not present at recorded line {line}")
    if kind not in {"component", "element"}:
        errors.append(f"{route}:{line}: invalid reference kind {kind!r}")
        return errors
    if kind == "element":
        if import_path is not None or reference.get("resolved_path") is not None:
            errors.append(f"{route}:{line}: element {name} carries an import")
        return errors
    modules = imports.get(component_root, [])
    if import_path is None:
        reason = reference.get("unresolved_because")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{route}:{line}: unresolved {name} has no reason")
        if not _has_local_definition(source, component_root) and len(modules) < 2:
            errors.append(
                f"{route}:{line}: {name} is recorded local/unresolved but has no local definition"
            )
        return errors
    if not isinstance(import_path, str) or import_path not in modules:
        errors.append(f"{route}:{line}: {name} does not match a live import from {import_path!r}")
        return errors
    if not import_path.startswith(("./", "../")):
        return errors
    expected = posixpath.normpath(posixpath.join(posixpath.dirname(route), import_path))
    if expected.startswith("../") or reference.get("resolved_path") != expected:
        errors.append(
            f"{route}:{line}: {name} resolves to {expected!r}, not {reference.get('resolved_path')!r}"
        )
        return errors
    target = repo_path(root, expected, f"resolved component {name}")
    candidates = [target] if target.suffix.lstrip(".") in extensions else []
    candidates.extend(target.with_suffix(f".{extension}") for extension in extensions)
    candidates.extend(target / f"index.{extension}" for extension in extensions)
    if not any(candidate.is_file() for candidate in candidates):
        errors.append(f"{route}:{line}: resolved component {expected!r} does not exist")
    return errors


def _validate_screens(root: Path, config: dict[str, Any]) -> tuple[set[str], int, list[str]]:
    surface = config.get("surface")
    if not isinstance(surface, dict):
        raise LedgerError(".vds/config.toml has no [surface] table")
    ledger_path = repo_path(root, surface.get("screens_ledger"), "screens ledger")
    ledger = load_yaml(ledger_path)
    if not isinstance(ledger, dict) or set(ledger) != SCREEN_KEYS:
        raise LedgerError("screens ledger has unexpected top-level fields")
    if ledger["schema_version"] != 1 or ledger["generated_by"] != "vds ledger screens":
        raise LedgerError("screens ledger has an unsupported schema or generator")
    configured_globs = surface.get("screen_globs")
    if ledger["source_globs"] != configured_globs:
        raise LedgerError("screens ledger source_globs differ from .vds/config.toml")
    files = _screen_files(root, configured_globs)
    expected_routes = {path.relative_to(root).as_posix() for path in files}
    rows = ledger.get("screens")
    if not isinstance(rows, list):
        raise LedgerError("screens ledger rows are not a list")
    actual_routes = [row.get("route") for row in rows if isinstance(row, dict)]
    if len(actual_routes) != len(rows) or len(set(actual_routes)) != len(actual_routes):
        raise LedgerError("screens ledger has a malformed or duplicate route")
    errors: list[str] = []
    if set(actual_routes) != expected_routes:
        errors.append(
            "screens ledger route set is stale "
            f"(missing={sorted(expected_routes - set(actual_routes))}, "
            f"extra={sorted(set(actual_routes) - expected_routes)})"
        )
    file_digests = {path.relative_to(root).as_posix(): sha256(path) for path in files}
    source_rows = [[route, file_digests[route]] for route in sorted(file_digests)]
    expected_source_digest = value_digest(source_rows)
    if require_digest(ledger["source_digest"], "screens source_digest") != expected_source_digest:
        errors.append("screens ledger source_digest is stale")
    reference_count = 0
    extensions = tuple(surface.get("component_extensions", []))
    for row in rows:
        if not isinstance(row, dict) or set(row) != SCREEN_ROW_KEYS:
            errors.append("screens ledger contains a malformed screen row")
            continue
        route = row["route"]
        if route not in file_digests:
            continue
        if require_digest(row["digest"], f"{route} digest") != file_digests[route]:
            errors.append(f"{route}: source digest is stale")
        references = row["references"]
        if not isinstance(references, list):
            errors.append(f"{route}: references are not a list")
            continue
        reference_count += len(references)
        source = repo_path(root, route, "screen route").read_text(encoding="utf-8")
        lines = source.splitlines()
        imports = _import_bindings(source)
        for reference in references:
            errors.extend(
                _validate_reference(root, route, source, lines, imports, extensions, reference)
            )
    content = {key: ledger[key] for key in SCREEN_KEYS - {"generated_at", "content_digest"}}
    if require_digest(ledger["content_digest"], "screens content_digest") != value_digest(content):
        errors.append("screens ledger content_digest does not witness its content")
    return set(actual_routes), reference_count, errors


def _validate_route_source(
    root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    match = _ROUTE_SOURCE_RE.fullmatch(str(manifest.get("source", "")))
    if match is None:
        return ["route manifest source is not a digest-bound capture + metrics pair"]
    capture_path = repo_path(root, match.group("capture"), "route capture source")
    metrics_path = capture_path.with_name("metrics.json")
    if sha256(capture_path) != match.group("capture_digest"):
        errors.append("route manifest capture digest is stale")
    if sha256(metrics_path) != match.group("metrics_digest"):
        errors.append("route manifest metrics digest is stale")
    capture = load_json(capture_path)
    if not isinstance(capture, dict):
        return errors + ["route capture manifest is not an object"]
    expected_limits = {
        "status": "captured_unreviewed",
        "visualVerdict": "not_assessed",
        "vdsReviewsUpdated": False,
    }
    for key, expected in expected_limits.items():
        if capture.get(key) != expected:
            errors.append(f"route capture {key} must remain {expected!r}")
    review = config.get("review", {})
    if not isinstance(review, dict):
        raise LedgerError(".vds/config.toml [review] must be a table")
    configured_scope = review.get("capture_source_scope", DEFAULT_CAPTURE_SOURCE_SCOPE)
    if (
        not isinstance(configured_scope, (list, tuple))
        or not configured_scope
        or not all(isinstance(item, str) for item in configured_scope)
        or len(set(configured_scope)) != len(configured_scope)
    ):
        raise LedgerError("capture_source_scope must be a non-empty unique string list")
    expected_scope = tuple(configured_scope)
    source_binding = capture.get("sourceBinding")
    if not isinstance(source_binding, dict):
        errors.append("route capture has no sourceBinding")
    else:
        if source_binding.get("status") != "current_at_capture":
            errors.append("route capture sourceBinding status is not current_at_capture")
        if source_binding.get("digestAlgorithm") != "sha256-path-type-content-v1":
            errors.append("route capture sourceBinding digest algorithm is unsupported")
        if source_binding.get("scope") != list(expected_scope):
            errors.append(
                "route capture sourceBinding scope differs from the governed source scope"
            )
        before = source_binding.get("digestBeforeCapture")
        after = source_binding.get("digestAfterCapture")
        if (
            not isinstance(before, str)
            or not re.fullmatch(r"[0-9a-f]{64}", before)
            or before != after
            or source_binding.get("sourceUnchangedDuringCapture") is not True
        ):
            errors.append("route capture sourceBinding does not prove an unchanged capture")
        elif source_binding.get("scope") == list(expected_scope):
            current_digest = source_tree_digest(root, expected_scope)
            if current_digest != after:
                errors.append(
                    "route capture source digest is stale "
                    f"(captured={after}, current={current_digest})"
                )
    limitations = " ".join(manifest.get("doesNotCover", [])).lower()
    for phrase in (
        "no non-invented framedigest",
        "no framedigest, sign-off",
        "no signed full-frame target",
    ):
        if phrase not in limitations:
            errors.append(f"route manifest lost evidence limitation: {phrase}")
    return errors


def _validate_routes(
    root: Path,
    config: dict[str, Any],
    screen_routes: set[str],
    route_source: str,
) -> tuple[int, list[str]]:
    source = load_json(repo_path(root, route_source, "route source manifest"))
    ledger_path = repo_path(
        root,
        config.get("review", {}).get("route_manifest", ".vds/ledgers/routes.yaml"),
        "route ledger",
    )
    ledger = load_yaml(ledger_path)
    if not isinstance(source, dict) or set(source) != ROUTE_KEYS:
        raise LedgerError("route source manifest has unexpected fields")
    if not isinstance(ledger, dict) or set(ledger) != ROUTE_KEYS:
        raise LedgerError("route ledger has unexpected fields")
    errors = _validate_route_source(root, config, source)
    source_content = {key: source[key] for key in ROUTE_KEYS - {"contentDigest"}}
    expected_digest = value_digest(source_content)
    if require_digest(source["contentDigest"], "route source contentDigest") != expected_digest:
        errors.append("route source contentDigest does not witness its content")
    if require_digest(ledger["contentDigest"], "route ledger contentDigest") != expected_digest:
        errors.append("route ledger contentDigest is stale")
    if ledger != source:
        errors.append("route ledger is not the canonical output of its source manifest")
    routes = ledger.get("routes")
    if not isinstance(routes, list) or not all(isinstance(item, str) for item in routes):
        raise LedgerError("route ledger routes are not a string list")
    if len(routes) < MIN_ROUTE_FILES:
        errors.append(f"route ledger has {len(routes)} routes; expected at least {MIN_ROUTE_FILES}")
    if routes != sorted(set(routes)):
        errors.append("route ledger routes must be sorted and unique")
    for route in routes:
        if route not in screen_routes:
            errors.append(f"route ledger entry is absent from the live screens ledger: {route}")
    return len(routes), errors


def check_repository(root: Path = ROOT, *, route_source: str = ROUTE_SOURCE_PATH) -> Report:
    try:
        config_path = repo_path(root, CONFIG_PATH, "VDS config")
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        screen_routes, reference_count, errors = _validate_screens(root, config)
        route_count, route_errors = _validate_routes(root, config, screen_routes, route_source)
        errors.extend(route_errors)
        return Report(len(screen_routes), reference_count, route_count, tuple(errors))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, LedgerError) as exc:
        return Report(0, 0, 0, (str(exc),))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--route-source", default=ROUTE_SOURCE_PATH)
    args = parser.parse_args(argv)
    report = check_repository(args.root.resolve(), route_source=args.route_source)
    print(
        "VDS ledger scan: "
        f"{report.screen_count} screens, {report.reference_count} references, "
        f"{report.route_count} visual-review routes"
    )
    if report.errors:
        print("VDS ledger gate failed:", file=sys.stderr)
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "Regenerate with `vds ledger screens` and `vds ledger routes --from "
            f"{args.route_source}`.",
            file=sys.stderr,
        )
        return 1
    print("VDS ledger staleness: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
