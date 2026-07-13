"""Herdr adapter: host terminal control stays behind governed verbs."""

import asyncio

import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.herdr import HerdrAdapter, _process_env, _stack_env
from boltrig.models import GrantSet, InvocationContext

T = "acme"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


class _HungProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.waits = 0

    async def communicate(self):
        await asyncio.sleep(60)

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waits += 1
        return self.returncode


@pytest.mark.invariant("FR-HOST-01")
def test_herdr_adapter_declares_read_and_mutating_verbs():
    verbs = {spec.verb_id: spec for spec in HerdrAdapter().describe()}
    assert {"herdr.snapshot", "herdr.pane.read", "herdr.pane.run"}.issubset(verbs)
    assert verbs["herdr.snapshot"].consequence == "low"
    assert verbs["herdr.pane.run"].consequence == "high"


@pytest.mark.invariant("FR-HOST-02")
async def test_herdr_snapshot_runs_cli_and_returns_structured_json():
    seen = []

    async def runner(argv):
        seen.append(argv)
        return 0, '{"result":{"snapshot":{"panes":[]}}}', ""

    adapter = HerdrAdapter(bin_path="herdr", command_runner=runner)
    result = await adapter.execute("herdr.snapshot", {}, None, _ctx())

    assert result.ok
    assert seen == [["herdr", "api", "snapshot"]]
    assert result.output["result"]["result"]["snapshot"]["panes"] == []


@pytest.mark.invariant("FR-HOST-03")
async def test_herdr_pane_run_uses_argv_not_shell_and_no_credentials():
    seen = []

    async def runner(argv):
        seen.append(argv)
        return 0, "ok", ""

    adapter = HerdrAdapter(bin_path="herdr", command_runner=runner)
    cred = Credential(id="secret", kind="api_key", material={"value": "do-not-pass"})
    result = await adapter.execute(
        "herdr.pane.run", {"pane_id": "p1", "command": "echo hello"}, cred, _ctx()
    )

    assert result.ok
    assert seen == [["herdr", "pane", "run", "p1", "echo hello"]]
    assert "do-not-pass" not in repr(seen)
    assert "credential" not in repr(result.output).lower()


@pytest.mark.invariant("FR-HOST-04")
async def test_herdr_unavailable_maps_to_retryable_adapter_failure():
    async def runner(_argv):
        return 127, "", "herdr command not found"

    result = await HerdrAdapter(command_runner=runner).execute(
        "herdr.snapshot", {}, None, _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.retryable


@pytest.mark.invariant("FR-HOST-14")
async def test_herdr_timeout_terminates_child(monkeypatch):
    proc = _HungProcess()

    async def create_subprocess_exec(*_argv, **_kwargs):
        return proc

    monkeypatch.setattr(
        "boltrig.adapters.builtin.herdr.asyncio.create_subprocess_exec",
        create_subprocess_exec,
    )

    code, stdout, stderr = await HerdrAdapter(timeout=0.001)._run(
        ["herdr", "status", "server"]
    )

    assert (code, stdout, stderr) == (124, "", "herdr command timed out")
    assert proc.terminated
    assert not proc.killed
    assert proc.waits == 1


@pytest.mark.invariant("FR-HOST-09")
def test_herdr_uses_stack_owned_home_when_configured(tmp_path):
    home = tmp_path / "herdr"

    env = _stack_env(str(home))

    assert env["HOME"] == str(home / "home")
    assert env["XDG_CONFIG_HOME"] == str(home / "config")
    assert env["XDG_DATA_HOME"] == str(home / "data")
    assert env["XDG_STATE_HOME"] == str(home / "state")
    assert env["HERDR_CONFIG_PATH"] == str(home / "config" / "config.toml")


@pytest.mark.invariant("FR-HOST-14")
def test_herdr_child_env_does_not_inherit_user_or_provider_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/home/will")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/will/.config")
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/home/will/.config/herdr/socket")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user")
    monkeypatch.setenv("RUNPOD_API_KEY", "rpa-user")

    env = _process_env(str(tmp_path / "herdr"))

    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HOME"] == str(tmp_path / "herdr" / "home")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "herdr" / "config")
    assert env["HERDR_CONFIG_PATH"] == str(tmp_path / "herdr" / "config" / "config.toml")
    assert "HERDR_SOCKET_PATH" not in env
    assert "OPENAI_API_KEY" not in env
    assert "RUNPOD_API_KEY" not in env
