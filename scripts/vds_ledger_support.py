"""Strict parsing and digest helpers for the repository-owned VDS ledger gate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class LedgerError(ValueError):
    """A ledger cannot be checked safely."""


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


# VDS digests the serialized timestamp string, not a language-specific date.
_UniqueSafeLoader.yaml_implicit_resolvers = {
    key: [
        (tag, expression)
        for tag, expression in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise LedgerError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _unique_mapping,
)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LedgerError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueSafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError, LedgerError) as exc:
        raise LedgerError(f"cannot load {path}: {exc}") from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, LedgerError) as exc:
        raise LedgerError(f"cannot load {path}: {exc}") from exc


def repo_path(root: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise LedgerError(f"{label} is not a repository-relative POSIX path: {raw!r}")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != raw:
        raise LedgerError(f"{label} escapes or is not normalized: {raw!r}")
    path = root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise LedgerError(f"{label} escapes the repository: {raw!r}") from exc
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise LedgerError(f"cannot digest {path}: {exc}") from exc
    return f"sha256:{digest.hexdigest()}"


def value_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise LedgerError(f"{label} is not a sha256 digest: {value!r}")
    return value
