#!/usr/bin/env python3
"""Enforce inward-only dependencies for the thin orchestration core."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_STDLIB_MODULES = frozenset(
    getattr(
        sys,
        "stdlib_module_names",
        {
            "__future__",
            "collections",
            "dataclasses",
            "datetime",
            "enum",
            "json",
            "pathlib",
            "typing",
        },
    )
)

_LAYER_IMPORTS = {
    "domain": ("boltrig.fleet.domain", "boltrig.models"),
    "ports": ("boltrig.fleet.ports", "boltrig.fleet.domain", "boltrig.models"),
    "application": (
        "boltrig.fleet.application",
        "boltrig.fleet.domain",
        "boltrig.fleet.ports",
        "boltrig.models",
    ),
    # The innermost layer: models may not reach back out into fleet. This is the
    # gate that keeps a record from carrying a fleet-owned type, and so keeps a
    # value derivable from a record from also being stored beside it.
    "models": ("boltrig.models",),
}

# Each layer's own package is the root that is scanned for it, so a new layer is
# declared once above rather than special-cased against a single hardcoded tree.
_LAYER_ROOTS = {
    "domain": ("boltrig", "fleet", "domain"),
    "ports": ("boltrig", "fleet", "ports"),
    "application": ("boltrig", "fleet", "application"),
    "models": ("boltrig", "models"),
}

# The kernel composes every sibling package, so an allow-list cannot express its
# boundary; it is gated by a DENY-list instead (AGENTS.md "Layering &
# severability": kernel/ imports nothing from fleet/ or the sidecars).
_KERNEL_ROOT = ("boltrig", "kernel")
_KERNEL_FORBIDDEN = ("boltrig.fleet", "services")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    dependency: str
    reason: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}: {self.dependency}"


@dataclass(frozen=True)
class Report:
    checked_files: int
    violations: tuple[Violation, ...]


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(module_name: str, is_package: bool, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = module_name if is_package else module_name.rpartition(".")[0]
    parts = package.split(".") if package else []
    ascend = node.level - 1
    if ascend > len(parts):
        return "<invalid-relative-import>"
    base = parts[: len(parts) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _is_allowed(module: str, allowed: tuple[str, ...]) -> bool:
    root = module.split(".", 1)[0]
    if root in _STDLIB_MODULES:
        return True
    return any(module == prefix or module.startswith(prefix + ".") for prefix in allowed)


def _is_forbidden(module: str, forbidden: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)


def _dynamic_import_name(node: ast.Call, dynamic_names: set[str]) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id in dynamic_names:
        return node.func.id
    if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
        return "import_module"
    if (
        isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Name)
        and node.func.func.id == "getattr"
        and len(node.func.args) >= 2
        and isinstance(node.func.args[1], ast.Constant)
        and node.func.args[1].value in {"__import__", "import_module"}
    ):
        return f"getattr(..., {node.func.args[1].value!r})"
    return None


def _scan_file(path: Path, root: Path, layer: str) -> list[Violation]:
    relative = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module_name = _module_name(path, root)
    allowed = _LAYER_IMPORTS[layer]
    violations: list[Violation] = []
    dynamic_names = {"__import__", "eval", "exec"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            dependency = _resolve_from(module_name, path.name == "__init__.py", node)
            if dependency in {"builtins", "importlib"}:
                for alias in node.names:
                    if alias.name in {"__import__", "eval", "exec", "import_module"}:
                        dynamic_names.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        dependencies: tuple[str, ...] = ()
        line = int(getattr(node, "lineno", 1))
        if isinstance(node, ast.Import):
            dependencies = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            dependencies = (_resolve_from(module_name, path.name == "__init__.py", node),)
        for dependency in dependencies:
            if not _is_allowed(dependency, allowed):
                violations.append(
                    Violation(relative, line, dependency, f"{layer} dependency points outward")
                )
        if isinstance(node, ast.Call):
            dynamic_name = _dynamic_import_name(node, dynamic_names)
            if dynamic_name is not None:
                violations.append(
                    Violation(relative, node.lineno, dynamic_name, "dynamic import bypasses gate")
                )
    return violations


def _scan_kernel_file(path: Path, root: Path) -> list[Violation]:
    """The deny-list twin of ``_scan_file`` for the kernel layer."""
    relative = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    module_name = _module_name(path, root)
    violations: list[Violation] = []
    dynamic_names = {"__import__", "eval", "exec"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            dependency = _resolve_from(module_name, path.name == "__init__.py", node)
            if dependency in {"builtins", "importlib"}:
                for alias in node.names:
                    if alias.name in {"__import__", "eval", "exec", "import_module"}:
                        dynamic_names.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        dependencies: tuple[str, ...] = ()
        line = int(getattr(node, "lineno", 1))
        if isinstance(node, ast.Import):
            dependencies = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            dependencies = (_resolve_from(module_name, path.name == "__init__.py", node),)
        for dependency in dependencies:
            if _is_forbidden(dependency, _KERNEL_FORBIDDEN):
                violations.append(
                    Violation(relative, line, dependency, "kernel dependency points outward")
                )
        if isinstance(node, ast.Call):
            dynamic_name = _dynamic_import_name(node, dynamic_names)
            if dynamic_name is not None:
                violations.append(
                    Violation(relative, node.lineno, dynamic_name, "dynamic import bypasses gate")
                )
    return violations


def check_repository(root: Path = ROOT) -> Report:
    violations: list[Violation] = []
    checked = 0
    for layer in _LAYER_IMPORTS:
        layer_root = root.joinpath(*_LAYER_ROOTS[layer])
        if not layer_root.is_dir():
            violations.append(
                Violation(
                    layer_root.relative_to(root).as_posix(),
                    1,
                    layer,
                    "required orchestration layer is missing",
                )
            )
            continue
        for path in sorted(layer_root.rglob("*.py")):
            checked += 1
            violations.extend(_scan_file(path, root, layer))
    kernel_root = root.joinpath(*_KERNEL_ROOT)
    if kernel_root.is_dir():
        for path in sorted(kernel_root.rglob("*.py")):
            checked += 1
            violations.extend(_scan_kernel_file(path, root))
    return Report(checked, tuple(sorted(violations, key=lambda item: (item.path, item.line))))


def main() -> int:
    report = check_repository()
    if report.violations:
        print("Thin-orchestration architecture violations:", file=sys.stderr)
        for violation in report.violations:
            print(f"  {violation.render()}", file=sys.stderr)
        return 1
    print(f"architecture boundary clean: {report.checked_files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
