from __future__ import annotations

import asyncio

import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.browser_cli import BrowserCliAdapter, _process_env
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

    async def communicate(self, _stdin=None):
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


def test_browser_cli_adapter_declares_narrow_browser_verbs():
    verbs = {spec.verb_id: spec for spec in BrowserCliAdapter().describe()}

    assert verbs["browser.doctor"].consequence == "low"
    assert verbs["browser.page.info"].consequence == "low"
    assert verbs["browser.tab.open"].consequence == "high"
    assert verbs["browser.remote.start"].consequence == "high"
    assert "browser.script.run" not in verbs


async def test_browser_tab_open_runs_browser_use_python_over_stdin():
    seen = {}

    async def runner(argv, stdin, env):
        seen.update({"argv": argv, "stdin": stdin, "env": env})
        return 0, '{"url":"https://example.com","title":"Example"}', ""

    adapter = BrowserCliAdapter(
        bin_path="browser-use",
        command_runner=runner,
        allowed_domains=("example.com",),
    )
    cred = Credential(id="SECRET", kind="api_key", material={"value": "do-not-pass"})
    result = await adapter.execute(
        "browser.tab.open",
        {"url": "https://example.com/path?q=1", "name": "work"},
        cred,
        _ctx(),
    )

    assert result.ok
    assert seen["argv"] == ["browser-use"]
    assert seen["env"] == {"BU_NAME": "work"}
    assert 'new_tab("https://example.com/path?q=1")' in seen["stdin"]
    assert "do-not-pass" not in repr(seen)
    assert result.output["result"]["title"] == "Example"


async def test_browser_cli_rejects_private_or_disallowed_navigation():
    calls = []

    async def runner(argv, stdin, env):
        calls.append((argv, stdin, env))
        return 0, "{}", ""

    adapter = BrowserCliAdapter(command_runner=runner, allowed_domains=("example.com",))

    private = await adapter.execute("browser.tab.open", {"url": "http://127.0.0.1"}, None, _ctx())
    disallowed = await adapter.execute(
        "browser.tab.open", {"url": "https://evil.example"}, None, _ctx()
    )

    assert not private.ok
    assert not disallowed.ok
    assert calls == []


async def test_browser_page_info_and_remote_daemon_commands_are_structured():
    seen = []

    async def runner(argv, stdin, env):
        seen.append((argv, stdin, env))
        return 0, '{"ok":true}', ""

    adapter = BrowserCliAdapter(bin_path="browser-use", command_runner=runner)

    assert (await adapter.execute("browser.page.info", {"name": "work"}, None, _ctx())).ok
    assert (await adapter.execute("browser.remote.start", {"name": "work"}, None, _ctx())).ok
    assert (await adapter.execute("browser.remote.stop", {"name": "work"}, None, _ctx())).ok
    assert (await adapter.execute("browser.auth.status", {}, None, _ctx())).ok

    assert seen[0] == (
        ["browser-use"],
        "import json\nprint(json.dumps(page_info(), default=str))\n",
        {"BU_NAME": "work"},
    )
    assert seen[1] == (["browser-use"], 'start_remote_daemon("work")\n', {})
    assert seen[2] == (["browser-use"], 'stop_remote_daemon("work")\n', {})
    assert seen[3] == (["browser-use", "auth", "status"], None, {})


async def test_browser_cli_unavailable_maps_to_retryable_failure():
    async def runner(argv, stdin, env):
        return 127, "", "browser-use command not found"

    result = await BrowserCliAdapter(command_runner=runner).execute(
        "browser.doctor", {}, None, _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.retryable


@pytest.mark.invariant("FR-HOST-11")
async def test_browser_cli_timeout_terminates_child(monkeypatch):
    proc = _HungProcess()

    async def create_subprocess_exec(*_argv, **_kwargs):
        return proc

    monkeypatch.setattr(
        "boltrig.adapters.builtin.browser_cli.asyncio.create_subprocess_exec",
        create_subprocess_exec,
    )

    code, stdout, stderr = await BrowserCliAdapter(timeout=0.001)._run(
        ["browser-use", "--doctor"], None, {}
    )

    assert (code, stdout, stderr) == (124, "", "browser-use command timed out")
    assert proc.terminated
    assert not proc.killed
    assert proc.waits == 1


@pytest.mark.invariant("FR-HOST-11")
def test_browser_cli_uses_stack_owned_home_when_configured(monkeypatch):
    monkeypatch.setenv("HOME", "/home/will")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/will/.config")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLI_HOME", "/var/lib/boltrig/browser-cli")

    env = _process_env({"BU_NAME": "work"})

    assert env["HOME"] == "/var/lib/boltrig/browser-cli/home"
    assert env["XDG_CONFIG_HOME"] == "/var/lib/boltrig/browser-cli/config"
    assert env["XDG_DATA_HOME"] == "/var/lib/boltrig/browser-cli/data"
    assert env["XDG_STATE_HOME"] == "/var/lib/boltrig/browser-cli/state"
    assert env["XDG_CACHE_HOME"] == "/var/lib/boltrig/browser-cli/cache"
    assert env["BU_NAME"] == "work"


@pytest.mark.invariant("FR-HOST-13")
def test_browser_cli_child_env_does_not_inherit_user_or_provider_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/home/will")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user")
    monkeypatch.setenv("RUNPOD_API_KEY", "rpa-user")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "personal-browser-key")
    monkeypatch.setenv("BROWSER_USE_PROFILE_ID", "personal-profile")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLI_HOME", "/var/lib/boltrig/browser-cli")
    monkeypatch.delenv("BOLTRIG_BROWSER_CLOUD_POLICY", raising=False)

    env = _process_env({"BU_NAME": "work"})

    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HOME"] == "/var/lib/boltrig/browser-cli/home"
    assert env["BU_NAME"] == "work"
    assert "OPENAI_API_KEY" not in env
    assert "RUNPOD_API_KEY" not in env
    assert "BROWSER_USE_API_KEY" not in env
    assert "BROWSER_USE_PROFILE_ID" not in env


@pytest.mark.invariant("FR-HOST-13")
def test_browser_cli_cloud_profile_uses_only_stack_prefixed_handoff(monkeypatch):
    monkeypatch.setenv("BOLTRIG_BROWSER_CLI_HOME", "/var/lib/boltrig/browser-cli")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLOUD_POLICY", "stack")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLOUD_API_KEY", "stack-key")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLOUD_PROFILE_ID", "stack-profile")
    monkeypatch.setenv("BOLTRIG_BROWSER_CLOUD_PROJECT_ID", "stack-project")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "personal-key")
    monkeypatch.setenv("BROWSER_USE_PROFILE_ID", "personal-profile")

    env = _process_env({})

    assert env["BROWSER_USE_CLOUD"] == "true"
    assert env["BROWSER_USE_API_KEY"] == "stack-key"
    assert env["BROWSER_USE_CLOUD_API_KEY"] == "stack-key"
    assert env["BROWSER_USE_PROFILE_ID"] == "stack-profile"
    assert env["BROWSER_USE_PROJECT_ID"] == "stack-project"
    assert "BOLTRIG_BROWSER_CLOUD_API_KEY" not in env
    assert "BOLTRIG_BROWSER_CLOUD_PROFILE_ID" not in env
    assert "personal-key" not in repr(env)
    assert "personal-profile" not in repr(env)
