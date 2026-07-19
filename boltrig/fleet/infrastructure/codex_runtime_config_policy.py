"""Exact lexical policy values for disabled Codex runtime-config composition."""

from __future__ import annotations

import posixpath
import re
import tomllib
from pathlib import Path

from .skill_config import MAX_SKILL_CONFIG_BYTES, REVIEWED_SYSTEM_SKILLS_0_144_3

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class CodexRuntimeConfigError(ValueError):
    """A runtime config input could widen or ambiguously change cell policy."""


def validate_cell_id(value: object) -> str:
    return _ascii_identifier("cell id", value, _IDENTIFIER)


def validate_model_id(value: object) -> str:
    return _ascii_identifier("model id", value, _MODEL_ID)


def _ascii_identifier(label: str, value: object, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise CodexRuntimeConfigError(f"{label} is invalid")
    return value


def validate_digest(label: str, value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CodexRuntimeConfigError(f"{label} must be an exact lowercase SHA-256 digest")
    return value


def _path(label: str, value: object) -> Path:
    if type(value) is not type(Path("/")):
        raise CodexRuntimeConfigError(f"{label} must be an exact pathlib POSIX path")
    rendered = value.as_posix()
    if (
        not rendered
        or "\x00" in rendered
        or not posixpath.isabs(rendered)
        or rendered.startswith("//")
        or posixpath.normpath(rendered) != rendered
        or Path(rendered) != value
        or any(ord(character) < 0x20 or ord(character) > 0x7E for character in rendered)
    ):
        raise CodexRuntimeConfigError(f"{label} must be a normalized absolute ASCII POSIX path")
    return value


def validate_cell_paths(
    cell_root: object, codex_home: object, helper: object
) -> tuple[Path, Path, Path]:
    """Validate lexical paths; production must separately bind roots and reject symlinks.

    [2026] VJS-CC-VJS 5 G2 INVERTED THIS RULE. The helper previously had to be
    INSIDE the cell root, which is precisely the defect the court found: under one
    shared uid, a helper in a mutable cell root is rewritable by every sibling cell,
    so the App Server executes attacker code and hands over an attested bearer. The
    helper must now live OUTSIDE the cell tree entirely, on a path the cell uid
    cannot write; ``codex_cell_boundary`` proves that at runtime, and this is the
    lexical half of the same rule.
    """

    root = _path("cell root", cell_root)
    home = _path("Codex home", codex_home)
    auth_helper = _path("model auth helper", helper)
    if home.parent != root:
        raise CodexRuntimeConfigError("Codex home must be an exact child of the cell root")
    if auth_helper.is_relative_to(root):
        raise CodexRuntimeConfigError("model auth helper must live outside the mutable cell root")
    if root.is_relative_to(auth_helper.parent):
        raise CodexRuntimeConfigError("model auth helper directory must not contain the cell root")
    return root, home, auth_helper


def validate_ingress_socket_path(value: object) -> Path:
    """Validate the ingress socket path the shared helper receives on argv.

    The socket is named, not secret. Pointing it elsewhere yields no cross-cell
    bearer, because the attestor matches the connecting peer's OWN ancestor chain
    against the shared registry snapshot, so a cell that connects to a sibling's
    socket is still issued only its own scope.
    """

    return _path("ingress socket", value)


def validate_receipt_paths(
    cell_root: object, codex_home: object, helper: object
) -> tuple[Path, Path, Path]:
    if (
        type(cell_root) is not str
        or type(codex_home) is not str
        or type(helper) is not str
    ):
        raise CodexRuntimeConfigError("runtime config receipt paths are invalid")
    return validate_cell_paths(Path(cell_root), Path(codex_home), Path(helper))


def validated_skill_fragment(fragment: object, codex_home: Path) -> tuple[tuple[str, bool], ...]:
    if type(fragment) is not bytes or not fragment or len(fragment) > MAX_SKILL_CONFIG_BYTES:
        raise CodexRuntimeConfigError("skill config fragment is absent or unbounded")
    try:
        document = tomllib.loads(fragment.decode("utf-8", errors="strict"))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise CodexRuntimeConfigError("skill config fragment is malformed") from None
    if set(document) != {"skills"} or type(document["skills"]) is not dict:
        raise CodexRuntimeConfigError("skill config fragment has unknown fields")
    skills = document["skills"]
    if set(skills) != {"config"} or type(skills["config"]) is not list:
        raise CodexRuntimeConfigError("skill config fragment has unknown fields")
    return _validate_skill_entry_list(skills["config"], codex_home)


def validated_runtime_skill_entries(
    entries: tuple[tuple[str, bool], ...], codex_home: Path
) -> tuple[tuple[str, bool], ...]:
    raw_entries: list[object] = [
        {"path": path, "enabled": enabled} for path, enabled in entries
    ]
    return _validate_skill_entry_list(raw_entries, codex_home)


def _validate_skill_entry_list(
    raw_entries: list[object], codex_home: Path
) -> tuple[tuple[str, bool], ...]:
    expected_system = tuple(
        (str(codex_home / "skills" / ".system" / name / "SKILL.md"), False)
        for name in REVIEWED_SYSTEM_SKILLS_0_144_3
    )
    if not len(expected_system) <= len(raw_entries) <= len(expected_system) + 128:
        raise CodexRuntimeConfigError("skill config entry count is invalid")
    entries: list[tuple[str, bool]] = []
    for raw in raw_entries:
        if type(raw) is not dict or set(raw) != {"path", "enabled"}:
            raise CodexRuntimeConfigError("skill config entry has unknown fields")
        path, enabled = raw["path"], raw["enabled"]
        if type(path) is not str or type(enabled) is not bool:
            raise CodexRuntimeConfigError("skill config entry has invalid values")
        entries.append((_path("skill config path", Path(path)).as_posix(), enabled))
    result = tuple(entries)
    if result[: len(expected_system)] != expected_system:
        raise CodexRuntimeConfigError("reviewed system skills are not exactly disabled")
    _validate_selected_skills(result[len(expected_system) :], codex_home)
    return result


def _validate_selected_skills(entries: tuple[tuple[str, bool], ...], codex_home: Path) -> None:
    expected_root = codex_home / "skills"
    names: list[str] = []
    for path_text, enabled in entries:
        path = Path(path_text)
        if not enabled or path.parent.parent != expected_root or path.name != "SKILL.md":
            raise CodexRuntimeConfigError("selected skill config entry escaped its exact root")
        names.append(_ascii_identifier("selected skill name", path.parent.name, _IDENTIFIER))
    if names != sorted(set(names)):
        raise CodexRuntimeConfigError("selected skill config entries must be sorted and unique")
