"""Deterministic App Server argv pinning for security-critical Codex config.

[2026] VJS-CC-VJS 6 H5. The per-cell ``config.toml`` lives in a CODEX_HOME the
shared cell uid owns, so a sibling cell can rewrite it before the App Server
reads it. argv cannot be rewritten: it is fixed at ``execve`` and no other
process can reach it. Pinning the security-critical keys on BOTH surfaces means
an attacker must win the one surface he cannot touch.

This does NOT close the vector, and nothing here should be read as saying it
does. Codex 0.144.3 MERGES table-valued ``-c`` overrides rather than replacing
them, so an attacker-added ``[mcp_servers.attacker]`` survives every override
expressible on argv, and any leaf not named here is his to set. That is why G3
stays open and ``production_ready`` stays False. This is defence in depth, which
is what H5 ordered it to be.

``auth.args`` is pinned as well as ``auth.command``, though the court named only
the latter. Pinning the command without its arguments pins the PROGRAM but not
its TARGET: a rewritten config could still aim the pinned helper at a SIBLING
cell's ingress socket and be handed that cell's bearer. Both, or neither.

``name`` and ``wire_api`` are pinned for a different reason, found by running the
pinned binary rather than by reading it: a provider table assembled purely from
overrides is rejected at startup with "provider name must not be empty". A pin
set that cannot start the cell is not a pin set, so the required fields travel
with the ones we actually care about.

Every argument is derived from the same validated values that render the TOML, so
the file and the command line cannot disagree. Nothing is stored beside the
record and then checked for agreement with it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_MODEL_PROVIDER_ID,
    CODEX_RUNTIME_DISABLED_FEATURES,
    CODEX_RUNTIME_PROVIDER_NAME,
    CODEX_RUNTIME_WIRE_API,
)

CODEX_APP_SERVER_BASE_ARGUMENTS = (
    "app-server",
    "--listen",
    "stdio://",
    "--strict-config",
)
_OVERRIDE_FLAG = "-c"
# A TOML bare key. The provider id is interpolated into a dotted -c path, and a
# segment needing quotes would change how that path parses, so refuse instead of
# emitting a path whose parse we have not verified.
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
_KEY_PATH = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\Z")
_PINNED_SCALAR_KEYS = 8
MAX_APP_SERVER_ARGUMENTS = len(CODEX_APP_SERVER_BASE_ARGUMENTS) + 2 * (
    _PINNED_SCALAR_KEYS + len(CODEX_RUNTIME_DISABLED_FEATURES)
)


class CodexAppServerArgumentError(ValueError):
    """A pinned App Server argument could not be derived or is not canonical."""


def _toml_string(value: str) -> str:
    """Render one TOML basic string exactly as the config renderer does."""

    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _printable_ascii(value: object) -> bool:
    return type(value) is str and all(0x20 <= ord(item) <= 0x7E for item in value)


def _pinned_assignments(
    *,
    cell_id: str,
    helper_path: str,
    socket_name: str,
    proxy_port: int,
    features: Mapping[str, bool],
) -> tuple[tuple[str, str], ...]:
    """The exact key/value pairs H5 pins, in the renderer's own order."""

    provider = f"model_providers.{CODEX_MODEL_PROVIDER_ID}"
    assignments = [
        ("model_provider", _toml_string(CODEX_MODEL_PROVIDER_ID)),
        ("approval_policy", _toml_string("never")),
        ("sandbox_mode", _toml_string("read-only")),
        (f"{provider}.name", _toml_string(CODEX_RUNTIME_PROVIDER_NAME)),
        (f"{provider}.wire_api", _toml_string(CODEX_RUNTIME_WIRE_API)),
        (f"{provider}.base_url", _toml_string(f"http://127.0.0.1:{proxy_port}/v1")),
        (f"{provider}.auth.command", _toml_string(helper_path)),
        (
            f"{provider}.auth.args",
            _toml_array(("--cell-id", cell_id, "--socket", socket_name)),
        ),
    ]
    assignments.extend(
        (f"features.{name}", "true" if features[name] else "false")
        for name in sorted(features)
    )
    return tuple(assignments)


def codex_app_server_arguments(
    *,
    cell_id: str,
    helper_path: str,
    socket_name: str,
    proxy_port: int,
    features: Mapping[str, bool] = CODEX_RUNTIME_DISABLED_FEATURES,
) -> tuple[str, ...]:
    """Derive the complete pinned argv for one cell from that cell's own record.

    Only keys already present in the rendered ``config.toml`` are pinned, and
    that is a correctness rule rather than a style one: ``--strict-config`` makes
    an unrecognised key a fatal startup error, so naming a key 0.144.3 does not
    know would take the cell down rather than harden it. Every key below is one
    the same binary already accepts from the generated file.
    """

    if (
        not _printable_ascii(cell_id)
        or not _printable_ascii(helper_path)
        or not _printable_ascii(socket_name)
        or type(proxy_port) is not int
        or not 1 <= proxy_port <= 65535
    ):
        raise CodexAppServerArgumentError("pinned argv inputs are not printable ASCII")
    if not isinstance(features, Mapping) or any(
        type(name) is not str or type(value) is not bool
        for name, value in features.items()
    ):
        raise CodexAppServerArgumentError("pinned argv features must be an exact bool mapping")
    if _BARE_KEY.fullmatch(CODEX_MODEL_PROVIDER_ID) is None:
        raise CodexAppServerArgumentError("model provider id is not a TOML bare key")
    arguments = list(CODEX_APP_SERVER_BASE_ARGUMENTS)
    for key, value in _pinned_assignments(
        cell_id=cell_id,
        helper_path=helper_path,
        socket_name=socket_name,
        proxy_port=proxy_port,
        features=features,
    ):
        if _KEY_PATH.fullmatch(key) is None:
            raise CodexAppServerArgumentError("pinned argv key path is not canonical")
        arguments.extend((_OVERRIDE_FLAG, f"{key}={value}"))
    return validate_app_server_arguments(tuple(arguments), cell_id=cell_id)


def validate_app_server_arguments(
    arguments: object, *, cell_id: str | None = None
) -> tuple[str, ...]:
    """Gate the SHAPE of an argv at a boundary that cannot see the receipt.

    This is not a second source of truth; ``codex_app_server_arguments`` is. It
    exists so the spawn seam, which deliberately knows nothing about runtime
    config composition, still refuses anything that is not the pinned base
    followed by well-formed ``-c key=value`` pairs, and still refuses an argv
    minted for a DIFFERENT cell than the layout being spawned.
    """

    if type(arguments) is not tuple or not all(
        _printable_ascii(argument) for argument in arguments
    ):
        raise CodexAppServerArgumentError("App Server arguments must be exact ASCII strings")
    base = len(CODEX_APP_SERVER_BASE_ARGUMENTS)
    if (
        arguments[:base] != CODEX_APP_SERVER_BASE_ARGUMENTS
        or (len(arguments) - base) % 2 != 0
        or len(arguments) > MAX_APP_SERVER_ARGUMENTS
    ):
        raise CodexAppServerArgumentError("App Server arguments must extend the pinned base")
    for index in range(base, len(arguments), 2):
        key, _, value = arguments[index + 1].partition("=")
        if (
            arguments[index] != _OVERRIDE_FLAG
            or _KEY_PATH.fullmatch(key) is None
            or not value
        ):
            raise CodexAppServerArgumentError("App Server overrides must be -c key=value pairs")
    if cell_id is not None:
        _require_own_cell(arguments[base:], cell_id)
    return arguments


def _require_own_cell(overrides: tuple[str, ...], cell_id: str) -> None:
    """Refuse an argv whose auth.args names another cell.

    The whole point of pinning auth.args is that the helper is aimed at THIS
    cell's ingress socket. An argv carrying a sibling's cell id would defeat that
    from the inside, so the spawn seam checks it even though the derivation
    cannot produce one.
    """

    expected = (
        f"model_providers.{CODEX_MODEL_PROVIDER_ID}.auth.args="
        f"[{_toml_string('--cell-id')}, {_toml_string(cell_id)}, "
    )
    if not any(override.startswith(expected) for override in overrides):
        raise CodexAppServerArgumentError("App Server arguments name another cell")


__all__ = [
    "CODEX_APP_SERVER_BASE_ARGUMENTS",
    "MAX_APP_SERVER_ARGUMENTS",
    "CodexAppServerArgumentError",
    "codex_app_server_arguments",
    "validate_app_server_arguments",
]
