"""Tests for the H5 App Server argv pinning ([2026] VJS-CC-VJS 6).

The court ordered the security-critical Codex configuration pinned on argv as
defence in depth, because argv is fixed at ``execve`` while the per-cell
``config.toml`` sits in a directory the shared cell uid owns. These tests hold
the two properties that make the pinning worth anything: the argv is DERIVED from
the record (so it cannot drift from the rendered TOML), and it carries nothing a
same-uid observer should not already see in ``/proc/<pid>/cmdline``.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.infrastructure.codex_runtime_config_argv import (
    CODEX_APP_SERVER_BASE_ARGUMENTS,
    MAX_APP_SERVER_ARGUMENTS,
    CodexAppServerArgumentError,
    codex_app_server_arguments,
    validate_app_server_arguments,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_RUNTIME_DISABLED_FEATURES,
)

_SOCKET = "@boltrig-mp-0123456789abcdef0123456789abcdef"
_HELPER = "/opt/boltrig/codex/model_auth_helper"


def _arguments(**overrides: object) -> tuple[str, ...]:
    kwargs: dict[str, object] = {
        "cell_id": "cell-001",
        "helper_path": _HELPER,
        "socket_name": _SOCKET,
        "proxy_port": 41234,
    }
    kwargs.update(overrides)
    return codex_app_server_arguments(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
def test_the_pinned_argv_extends_the_base_and_is_byte_stable() -> None:
    """Same inputs, same bytes: the argv is a function of the record, not a draw."""

    first = _arguments()
    assert first[:4] == CODEX_APP_SERVER_BASE_ARGUMENTS
    assert first == _arguments()
    # Four base arguments plus a -c pair for each pinned key and each feature.
    assert len(first) == 4 + 2 * (10 + len(CODEX_RUNTIME_DISABLED_FEATURES))
    assert len(first) <= MAX_APP_SERVER_ARGUMENTS


@pytest.mark.unit
def test_every_security_critical_key_the_court_named_is_pinned() -> None:
    overrides = dict(argument.split("=", 1) for argument in _arguments()[5::2])
    provider = "model_providers.boltrig_model_proxy"
    assert overrides["model_provider"] == '"boltrig_model_proxy"'
    assert overrides["approval_policy"] == '"never"'
    assert overrides["sandbox_mode"] == '"read-only"'
    assert overrides["agents.max_threads"] == "1"
    assert overrides["agents.max_depth"] == "1"
    assert overrides[f"{provider}.base_url"] == '"http://127.0.0.1:41234/v1"'
    assert overrides[f"{provider}.auth.command"] == f'"{_HELPER}"'
    # name and wire_api are pinned because a provider table assembled purely from
    # overrides is REJECTED at startup ("provider name must not be empty"). A pin
    # set that cannot start the cell is not a pin set.
    assert overrides[f"{provider}.name"]
    assert overrides[f"{provider}.wire_api"] == '"responses"'
    for feature in CODEX_RUNTIME_DISABLED_FEATURES:
        assert overrides[f"features.{feature}"] == "false"


@pytest.mark.unit
def test_auth_args_is_pinned_too_so_the_helper_cannot_be_aimed_elsewhere() -> None:
    """Pinning the program without its target would leave the vector open.

    A rewritten config could keep our pinned ``auth.command`` and change only
    ``auth.args``, aiming the pinned helper at a SIBLING cell's ingress socket,
    which would hand over that cell's bearer. So both are pinned or neither is.
    """

    overrides = dict(argument.split("=", 1) for argument in _arguments()[5::2])
    args = overrides["model_providers.boltrig_model_proxy.auth.args"]
    assert args == f'["--cell-id", "cell-001", "--socket", "{_SOCKET}"]'


@pytest.mark.unit
def test_the_abstract_socket_name_survives_as_a_toml_string() -> None:
    """The @ sigil is meaningless to TOML, so it must sit inside a basic string.

    A bare ``@boltrig-mp-...`` is not valid TOML, and the value is parsed as TOML
    by Codex before it ever reaches the helper.
    """

    joined = "\n".join(_arguments())
    assert f'"{_SOCKET}"' in joined
    assert "\x00" not in joined  # a literal NUL could never survive execve argv


@pytest.mark.unit
def test_nothing_secret_reaches_proc_cmdline() -> None:
    """argv is world-readable to every same-uid process, so it carries no secret.

    The bearer is delivered over the attested socket and the upstream key is
    injected server-side by the proxy. Neither may ever be pinned here.
    """

    joined = " ".join(_arguments()).lower()
    for forbidden in ("token", "bearer", "secret", "authorization", "api_key"):
        assert forbidden not in joined


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    [
        {"cell_id": "cell\x00001"},
        {"cell_id": "cell-é"},
        {"helper_path": "/opt/hel\nper"},
        {"socket_name": "@boltrig\x00"},
        {"proxy_port": 0},
        {"proxy_port": 65536},
        {"proxy_port": "41234"},
    ],
)
def test_unrepresentable_inputs_are_refused_rather_than_rendered(
    override: dict[str, object],
) -> None:
    """Fail closed: an argument we cannot render exactly is one we cannot pin."""

    with pytest.raises(CodexAppServerArgumentError):
        _arguments(**override)


@pytest.mark.unit
@pytest.mark.parametrize(
    "arguments",
    [
        ("app-server",),  # base truncated
        CODEX_APP_SERVER_BASE_ARGUMENTS + ("-c",),  # odd-length suffix
        CODEX_APP_SERVER_BASE_ARGUMENTS + ("--config", "model_provider=x"),  # not -c
        CODEX_APP_SERVER_BASE_ARGUMENTS + ("-c", "model_provider="),  # empty value
        CODEX_APP_SERVER_BASE_ARGUMENTS + ("-c", "not a key=x"),  # non-canonical key
        ("--strict-config",) + CODEX_APP_SERVER_BASE_ARGUMENTS,  # base not first
    ],
)
def test_the_spawn_seam_refuses_a_malformed_argv(arguments: tuple[str, ...]) -> None:
    with pytest.raises(CodexAppServerArgumentError):
        validate_app_server_arguments(arguments)


@pytest.mark.unit
def test_an_argv_minted_for_another_cell_is_refused() -> None:
    """The spawn seam checks the argv belongs to the layout it is spawning.

    The derivation cannot produce a mismatched argv, but the supervisor is a
    separate boundary that cannot see the receipt, so it verifies rather than
    trusts.
    """

    other = _arguments(cell_id="cell-999")
    validate_app_server_arguments(other, cell_id="cell-999")
    with pytest.raises(CodexAppServerArgumentError):
        validate_app_server_arguments(other, cell_id="cell-001")


@pytest.mark.unit
def test_an_over_long_argv_is_refused() -> None:
    padded = _arguments(
        mcp_server_url="http://kernel:8000/v1/mcp",
        mcp_bearer_env_var="BOLTRIG_CODEX_MCP_RUN_TOKEN",
    )
    assert len(padded) == MAX_APP_SERVER_ARGUMENTS  # the fullest lawful argv
    with pytest.raises(CodexAppServerArgumentError):
        validate_app_server_arguments(padded + ("-c", "features.hooks=false"))


@pytest.mark.unit
def test_a_non_tuple_argv_is_refused() -> None:
    with pytest.raises(CodexAppServerArgumentError):
        validate_app_server_arguments(list(CODEX_APP_SERVER_BASE_ARGUMENTS))
