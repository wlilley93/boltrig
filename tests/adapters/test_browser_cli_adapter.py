from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.browser_cli import BrowserCliAdapter
from boltrig.adapters.builtin.browser_commands import process_env
from boltrig.models import GrantSet, InvocationContext

T = "acme"


@pytest.fixture(autouse=True)
def _hermetic_dns(monkeypatch):
    """Resolve example.com without asking the machine's resolver.

    These tests exercise the EGRESS POLICY - allow-list, blocked domains,
    non-routable targets - and none of that needs live DNS. Without this they
    were env-dependent in both directions: they passed on a box whose resolver
    was healthy and failed with "egress refused: host did not resolve" whenever
    getaddrinfo was slow or unavailable, which is what happened twice under full
    suite load on 2026-07-26. A test that fails because of the network is not
    telling you anything about the code.

    The guard itself still runs: a public address is returned, so the
    non-routable / internal-address branch is evaluated exactly as before. Tests
    that need a different answer patch over this one.
    """
    monkeypatch.setattr(
        "boltrig.adapters.egress.resolve_host",
        lambda host: ["93.184.216.34"],
    )


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _frame_path(script: str) -> Path:
    match = re.search(r"_boltrig_save_frame\((\"(?:\\.|[^\"])*\")\)", script)
    assert match is not None
    return Path(json.loads(match.group(1)))


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
    assert verbs["browser.snapshot"].consequence == "low"
    assert verbs["browser.click"].consequence == "high"
    assert verbs["browser.type"].consequence == "high"
    assert verbs["browser.scroll"].idempotency_mode == "disabled"
    assert verbs["browser.frame.read"].idempotency_mode == "disabled"
    assert "browser.script.run" not in verbs
    assert "browser.cdp.call" not in verbs


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


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_snapshot_is_bounded_ephemeral_and_owner_scoped():
    jpeg = b"\xff\xd8bounded-frame\xff\xd9"

    async def runner(argv, stdin, env):
        assert argv == ["browser-use"]
        assert env == {"BU_NAME": "shared"}
        assert stdin is not None
        _frame_path(stdin).write_bytes(jpeg)
        return 0, json.dumps({
            "status": "ok",
            "page": {"url": "https://example.com", "title": "Example", "w": 1200, "h": 800},
        }), ""

    adapter = BrowserCliAdapter(command_runner=runner)
    captured = await adapter.execute("browser.snapshot", {"name": "shared"}, None, _ctx())

    assert captured.ok
    frame = captured.output["frame"]
    assert frame["url"] == "https://example.com"
    assert "data" not in frame

    read = await adapter.execute("browser.frame.read", {"id": frame["id"]}, None, _ctx())
    assert read.ok
    assert read.output["data"] == base64.b64encode(jpeg).decode("ascii")

    other = InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="other")
    denied = await adapter.execute("browser.frame.read", {"id": frame["id"]}, None, other)
    assert not denied.ok
    assert denied.error is not None
    assert denied.error.error_class.value == "not_found"


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_click_is_fixed_script_and_bound_to_displayed_frame():
    jpeg = b"\xff\xd8same-frame\xff\xd9"
    scripts: list[str] = []
    replies = ["ok", "stale_frame"]

    async def runner(_argv, stdin, _env):
        assert stdin is not None
        scripts.append(stdin)
        _frame_path(stdin).write_bytes(jpeg)
        status = replies.pop(0)
        payload = {
            "status": status,
            "page": {"url": "https://example.com", "title": "Example", "w": 1000, "h": 700},
        }
        if status == "ok" and len(scripts) > 1:
            payload["cursor"] = {"x": 12, "y": 34, "kind": "click"}
        return 0, json.dumps(payload), ""

    adapter = BrowserCliAdapter(command_runner=runner)
    first = await adapter.execute("browser.snapshot", {}, None, _ctx())
    assert first.ok
    clicked = await adapter.execute(
        "browser.click",
        {"expected_frame_id": first.output["frame"]["id"], "x": 12, "y": 34},
        None,
        _ctx(),
    )

    assert clicked.ok
    assert clicked.output["status"] == "stale_frame"
    action_script = scripts[1]
    assert f"actual != {json.dumps(hashlib.sha256(jpeg).hexdigest())}" in action_script
    assert "click_at_xy(12, 34, button=\"left\")" in action_script
    assert "exec(" not in action_script
    assert "eval(" not in action_script


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_type_quotes_text_and_rejects_unknown_frames_without_running():
    calls: list[str] = []

    async def runner(_argv, stdin, _env):
        calls.append(str(stdin))
        return 0, "{}", ""

    adapter = BrowserCliAdapter(command_runner=runner)
    result = await adapter.execute(
        "browser.type",
        {"expected_frame_id": "frame_missing", "text": "'); cdp('Runtime.evaluate') #"},
        None,
        _ctx(),
    )

    assert not result.ok
    assert calls == []


def test_browser_frames_are_mcp_resources_without_raw_browser_protocol():
    resources = BrowserCliAdapter().mcp_resources()

    assert len(resources) == 1
    assert resources[0].uri_prefix == "browser-frame://"
    assert resources[0].list_verb == "browser.frames.list"
    assert resources[0].read_verb == "browser.frame.read"


@pytest.mark.invariant("FR-HOST-11")
async def test_browser_cli_timeout_terminates_child(monkeypatch):
    proc = _HungProcess()

    async def create_subprocess_exec(*_argv, **_kwargs):
        return proc

    monkeypatch.setattr(
        "boltrig.adapters.builtin.script_base.asyncio.create_subprocess_exec",
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

    env = process_env({"BU_NAME": "work"})

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

    env = process_env({"BU_NAME": "work"})

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

    env = process_env({})

    assert env["BROWSER_USE_CLOUD"] == "true"
    assert env["BROWSER_USE_API_KEY"] == "stack-key"
    assert env["BROWSER_USE_CLOUD_API_KEY"] == "stack-key"
    assert env["BROWSER_USE_PROFILE_ID"] == "stack-profile"
    assert env["BROWSER_USE_PROJECT_ID"] == "stack-project"
    assert "BOLTRIG_BROWSER_CLOUD_API_KEY" not in env
    assert "BOLTRIG_BROWSER_CLOUD_PROFILE_ID" not in env
    assert "personal-key" not in repr(env)
    assert "personal-profile" not in repr(env)
