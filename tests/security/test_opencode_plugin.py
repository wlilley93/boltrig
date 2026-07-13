"""OpenCode operator plugin consumes Boltrig MCP handoff without global config."""

from __future__ import annotations

import os

import pytest

from boltrig.api.cli import main
from boltrig.fleet.opencode_plugin import install_opencode_plugin, plugin_path


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-16")
@pytest.mark.invariant("SEC-27")
def test_opencode_plugin_installer_writes_project_local_env_consumer(tmp_path):
    cfg = tmp_path / ".opencode"
    path = install_opencode_plugin(cfg)
    source = path.read_text(encoding="utf-8")

    assert path == cfg / "plugins" / "boltrig-mcp.js"
    assert plugin_path(cfg) == path
    assert "process.env.BOLTRIG_MCP_URL" in source
    assert "process.env.BOLTRIG_MCP_TOKEN" in source
    assert "process.env.BOLTRIG_MCP_SERVER_NAME" in source
    assert '"x-boltrig-mcp-token": TOKEN' in source
    assert "boltrig_mcp_list" in source
    assert "boltrig_mcp_call" in source

    rendered = source.lower()
    assert "opencode.json" not in rendered
    assert "run_token_secret" not in rendered
    assert "api_key" not in rendered
    assert not (cfg / "opencode.json").exists()
    assert not (tmp_path / "opencode.json").exists()


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-16")
def test_cli_installs_opencode_plugin_without_changing_cwd(tmp_path, capsys):
    before = os.getcwd()

    assert main(["opencode-plugin", "install", "--dir", str(tmp_path / ".opencode")]) == 0

    out = capsys.readouterr().out.strip()
    assert out.endswith(".opencode/plugins/boltrig-mcp.js")
    assert (tmp_path / ".opencode" / "plugins" / "boltrig-mcp.js").exists()
    assert os.getcwd() == before
