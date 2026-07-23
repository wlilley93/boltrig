"""The kernel-tools ``[mcp_servers.boltrig]`` config contract.

The read-only lane renders the bare empty ``[mcp_servers]`` table and is
byte-identical to before (pinned by test_codex_runtime_config.py). These pin
the tool-enabled half: exactly one server entry (url + bearer env var NAME),
the token never in the file/receipt/repr/argv, the MCP leaves argv-pinned like
every other per-cell value (H5), and the receipt re-render binding making any
MCP tamper fail closed.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import replace

import pytest

from boltrig.fleet.infrastructure.codex_runtime_config import (
    CodexRuntimeConfigError,
    ComposedCodexRuntimeConfig,
    compose_codex_runtime_config,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_MCP_BEARER_ENV_VAR,
)

from .test_codex_runtime_config import _request

_MCP_URL = "http://kernel:8000/v1/mcp"


def _mcp_request(**overrides: object):
    values: dict[str, object] = {
        "mcp_server_url": _MCP_URL,
        "mcp_bearer_env_var": CODEX_MCP_BEARER_ENV_VAR,
    }
    values.update(overrides)
    return replace(_request(), **values)


def test_kernel_tools_config_carries_exactly_one_mcp_server() -> None:
    composed = compose_codex_runtime_config(_mcp_request())
    document = tomllib.loads(composed.config_toml)

    assert document["mcp_servers"] == {
        "boltrig": {
            "url": _MCP_URL,
            "bearer_token_env_var": CODEX_MCP_BEARER_ENV_VAR,
        }
    }
    # The wall is otherwise unchanged.
    assert document["approval_policy"] == "never"
    assert document["sandbox_mode"] == "read-only"
    receipt = composed.receipt
    assert receipt.mcp_server_url == _MCP_URL
    assert receipt.mcp_bearer_env_var == CODEX_MCP_BEARER_ENV_VAR
    assert receipt.matches(composed.config_toml)
    assert receipt.production_ready is False


@pytest.mark.invariant("SEC-184")
def test_the_token_never_reaches_the_config_receipt_repr_or_argv() -> None:
    composed = compose_codex_runtime_config(_mcp_request())
    forbidden = ("run-token-secret", "http_headers", "env_http_headers", "bearer_token =")
    assert all(item not in composed.config_toml for item in forbidden)
    assert all(item not in repr(composed) for item in forbidden)
    assert all(item not in repr(composed.receipt) for item in forbidden)
    # argv pins the url and the env var NAME - never a token VALUE.
    arguments = composed.receipt.app_server_arguments
    assert not any("run-token-secret" in argument for argument in arguments)
    overrides = dict(argument.split("=", 1) for argument in arguments[5::2])
    assert overrides["mcp_servers.boltrig.url"] == f'"{_MCP_URL}"'
    assert overrides["mcp_servers.boltrig.bearer_token_env_var"] == (
        f'"{CODEX_MCP_BEARER_ENV_VAR}"'
    )


def test_read_only_config_is_unchanged_without_the_mcp_pair() -> None:
    composed = compose_codex_runtime_config(_request())
    assert tomllib.loads(composed.config_toml)["mcp_servers"] == {}
    assert composed.receipt.mcp_server_url is None
    arguments = composed.receipt.app_server_arguments
    assert not any("mcp_servers.boltrig" in argument for argument in arguments)


@pytest.mark.parametrize(
    "override",
    [
        {"mcp_bearer_env_var": None},  # half-wired
        {"mcp_server_url": None},
        {"mcp_server_url": "ftp://kernel:8000/v1/mcp"},
        {"mcp_server_url": "http://user:pw@kernel:8000/v1/mcp"},
        {"mcp_server_url": "http://kernel:8000/v1/mcp?key=1"},
        {"mcp_server_url": "http://kernel:8000/v1/mcp#frag"},
        {"mcp_server_url": "http://kernel:8000/v1/mcp\n"},
        {"mcp_bearer_env_var": "lowercase"},
        {"mcp_bearer_env_var": "HAS-DASH"},
    ],
)
def test_the_mcp_pair_fails_closed(override: dict[str, object]) -> None:
    with pytest.raises(CodexRuntimeConfigError):
        _mcp_request(**override)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('url = "http://kernel:8000/v1/mcp"', 'url = "http://attacker:9000/mcp"'),
        (
            'bearer_token_env_var = "BOLTRIG_CODEX_MCP_RUN_TOKEN"',
            'bearer_token_env_var = "ATTACKER_TOKEN"',
        ),
    ],
)
@pytest.mark.invariant("SEC-184")
def test_mcp_tamper_cannot_match_its_receipt(old: str, new: str) -> None:
    composed = compose_codex_runtime_config(_mcp_request())
    tampered = composed.config_toml.replace(old, new)
    encoded = tampered.encode("ascii")
    receipt = replace(
        composed.receipt,
        config_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        config_bytes=len(encoded),
    )
    with pytest.raises(CodexRuntimeConfigError, match="metadata"):
        ComposedCodexRuntimeConfig(tampered, receipt)


def test_an_added_second_mcp_server_cannot_match_its_receipt() -> None:
    composed = compose_codex_runtime_config(_mcp_request())
    widened = composed.config_toml + (
        '\n[mcp_servers.attacker]\nurl = "http://attacker:9000/mcp"\n'
    )
    encoded = widened.encode("ascii")
    receipt = replace(
        composed.receipt,
        config_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        config_bytes=len(encoded),
    )
    with pytest.raises(CodexRuntimeConfigError, match="metadata"):
        ComposedCodexRuntimeConfig(widened, receipt)
