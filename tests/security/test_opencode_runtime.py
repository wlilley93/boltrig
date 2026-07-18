"""OpenCodeRuntime: OpenCode as a pluggable coding-agent runtime."""

import json
import stat

import pytest

from boltrig.fleet.opencode_runtime import OpenCodeRuntime
from boltrig.fleet.runtime import build_runtime
from boltrig.models import AgentCapability, GrantSet, InvocationContext, ModelEndpoint

T = "acme"


def _cap(model_endpoint: str | None = "opencode-ornith") -> AgentCapability:
    return AgentCapability(
        "opencode-worker", T, "opencode", ["*"], 2, True, "standard",
        model_endpoint=model_endpoint,
    )


def _ctx(**extra):
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="opencode-worker",
        run_id="run-1",
        extra=extra,
    )


def _endpoint(base_url: str | None = "http://127.0.0.1:4096") -> ModelEndpoint:
    return ModelEndpoint(
        id="opencode-ornith",
        tenant_id=T,
        kind="opencode",
        model="ornith/deepreinforce-ai/Ornith-1.0-35B",
        base_url=base_url,
    )


@pytest.mark.invariant("FR-RUN-10")
def test_build_runtime_resolves_opencode():
    rt = build_runtime(_cap(), lambda _id: _endpoint())
    assert isinstance(rt, OpenCodeRuntime)
    assert rt.runtime == "opencode"


@pytest.mark.invariant("FR-RUN-11")
async def test_opencode_degrades_without_pinned_model():
    rt = OpenCodeRuntime(endpoint=None, command="opencode-does-not-matter")
    res = await rt.run("hello", _ctx(), tools=[])
    assert res.ok and res.degraded
    assert res.output["_degraded"] == {
        "runtime": "opencode",
        "reason": "no_model_endpoint",
    }


@pytest.mark.invariant("FR-RUN-12")
async def test_opencode_degrades_when_cli_missing():
    rt = OpenCodeRuntime(endpoint=_endpoint(), command="boltrig-no-such-opencode")
    res = await rt.run("hello", _ctx(), tools=[])
    assert res.ok and res.degraded
    assert res.output["_degraded"] == {
        "runtime": "opencode",
        "reason": "opencode_unavailable",
    }


@pytest.mark.invariant("FR-RUN-13")
@pytest.mark.invariant("SEC-27")
async def test_opencode_runs_json_cli_and_keeps_tool_credentials_out(tmp_path):
    script = tmp_path / "fake-opencode"
    sink = tmp_path / "argv.txt"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(sink)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        "print(json.dumps({'type':'message','text':'done'}))\n"
        "print(json.dumps({'usage': {'total_tokens': 9, 'cost_micros': 123}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    rt = OpenCodeRuntime(endpoint=_endpoint(), command=str(script))
    res = await rt.run("prompt", _ctx(repo_root=str(tmp_path)), tools=["ticket.read"])

    assert res.ok and not res.degraded
    assert res.summary == "done"
    assert res.tokens_used == 9
    assert res.cost_micros == 123
    argv = sink.read_text(encoding="utf-8")
    assert "--format" in argv and "json" in argv
    assert "--model" in argv and "ornith/deepreinforce-ai/Ornith-1.0-35B" in argv
    assert "ticket.read" not in argv
    assert "credential" not in argv.lower()


@pytest.mark.invariant("FR-RUN-15")
@pytest.mark.invariant("SEC-27")
async def test_opencode_scopes_mcp_token_to_env_and_revokes(tmp_path):
    script = tmp_path / "fake-opencode"
    argv_sink = tmp_path / "argv.json"
    env_sink = tmp_path / "env.json"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(argv_sink)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        f"pathlib.Path({str(env_sink)!r}).write_text(json.dumps({{\n"
        "  'url': os.environ.get('BOLTRIG_MCP_URL'),\n"
        "  'token': os.environ.get('BOLTRIG_MCP_TOKEN'),\n"
        "  'name': os.environ.get('BOLTRIG_MCP_SERVER_NAME'),\n"
        "}))\n"
        "token = os.environ.get('BOLTRIG_MCP_TOKEN', '')\n"
        "print(json.dumps({'type': 'message', 'text': 'token=' + token}))\n"
        "print('stderr=' + token, file=sys.stderr)\n"
        "print(json.dumps({'usage': {'total_tokens': 11, 'cost_micros': 321}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    revoked: list[str] = []
    rt = OpenCodeRuntime(
        endpoint=_endpoint(),
        command=str(script),
        mcp_url="http://kernel.example/v1/mcp",
        issue_token=lambda *a, **k: "RUN_TOKEN_SECRET",
        revoke_token=revoked.append,
    )
    res = await rt.run("prompt", _ctx(repo_root=str(tmp_path)), tools=["ticket.read"])

    assert res.ok and not res.degraded
    assert revoked == ["RUN_TOKEN_SECRET"]
    assert json.loads(env_sink.read_text(encoding="utf-8")) == {
        "url": "http://kernel.example/v1/mcp",
        "token": "RUN_TOKEN_SECRET",
        "name": "boltrig-kernel",
    }
    assert "RUN_TOKEN_SECRET" not in argv_sink.read_text(encoding="utf-8")
    assert "ticket.read" not in argv_sink.read_text(encoding="utf-8")
    assert "RUN_TOKEN_SECRET" not in repr(res.output)
    assert "RUN_TOKEN_SECRET" not in res.summary
    assert "[redacted]" in repr(res.output)


@pytest.mark.invariant("FR-RUN-15")
async def test_opencode_timeout_terminates_child_and_revokes(tmp_path):
    script = tmp_path / "slow-opencode"
    marker = tmp_path / "terminated.txt"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, signal, time\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "def handle(signum, frame):\n"
        "    marker.write_text('terminated', encoding='utf-8')\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, handle)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    revoked: list[str] = []
    rt = OpenCodeRuntime(
        endpoint=_endpoint(),
        command=str(script),
        mcp_url="http://kernel.example/v1/mcp",
        issue_token=lambda *a, **k: "RUN_TOKEN_SECRET",
        revoke_token=revoked.append,
        # Comfortably longer than a cold Python interpreter start so SIGTERM never
        # races ahead of the child arming its handler (a sub-second timeout let the
        # default action kill it before the marker was written). The contract under
        # test - timeout -> SIGTERM -> child handles -> token revoked - is unchanged.
        timeout=2.0,
    )
    res = await rt.run("prompt", _ctx(repo_root=str(tmp_path)), tools=[])

    assert res.ok and res.degraded
    assert res.output["_degraded"]["reason"] == "timeout"
    assert revoked == ["RUN_TOKEN_SECRET"]
    assert marker.read_text(encoding="utf-8") == "terminated"


@pytest.mark.invariant("FR-RUN-14")
def test_opencode_auto_approval_is_opt_in(monkeypatch):
    monkeypatch.delenv("BOLTRIG_OPENCODE_AUTO", raising=False)
    rt = OpenCodeRuntime(endpoint=_endpoint(), command="opencode")

    default_cmd = rt.build_command("prompt", _ctx(), tools=[])
    assert "--auto" not in default_cmd.argv

    env_cmd = OpenCodeRuntime(endpoint=_endpoint(), command="opencode")
    monkeypatch.setenv("BOLTRIG_OPENCODE_AUTO", "1")
    assert "--auto" in env_cmd.build_command("prompt", _ctx(), tools=[]).argv

    monkeypatch.delenv("BOLTRIG_OPENCODE_AUTO", raising=False)
    context_cmd = rt.build_command("prompt", _ctx(opencode_auto=True), tools=[])
    assert "--auto" in context_cmd.argv


@pytest.mark.invariant("FR-RUN-17")
def test_opencode_uses_stack_owned_home_when_configured(monkeypatch, tmp_path):
    home = tmp_path / "opencode"
    monkeypatch.setenv("BOLTRIG_OPENCODE_HOME", str(home))

    rt = OpenCodeRuntime(endpoint=_endpoint(), command="opencode")
    cmd = rt.build_command("prompt", _ctx(), tools=[])

    assert cmd.env["HOME"] == str(home / "home")
    assert cmd.env["XDG_CONFIG_HOME"] == str(home / "config")
    assert cmd.env["XDG_DATA_HOME"] == str(home / "data")
    assert cmd.env["XDG_STATE_HOME"] == str(home / "state")
    assert cmd.env["OPENCODE_CONFIG_DIR"] == str(home / "config" / "opencode")


@pytest.mark.invariant("FR-HOST-14")
async def test_opencode_child_env_does_not_inherit_user_or_provider_secrets(
    monkeypatch, tmp_path
):
    script = tmp_path / "fake-opencode"
    env_sink = tmp_path / "env.json"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib\n"
        f"pathlib.Path({str(env_sink)!r}).write_text(json.dumps({{\n"
        "  'home': os.environ.get('HOME'),\n"
        "  'config': os.environ.get('XDG_CONFIG_HOME'),\n"
        "  'opencode_config': os.environ.get('OPENCODE_CONFIG_DIR'),\n"
        "  'openai': os.environ.get('OPENAI_API_KEY'),\n"
        "  'runpod': os.environ.get('RUNPOD_API_KEY'),\n"
        "  'anthropic': os.environ.get('ANTHROPIC_API_KEY'),\n"
        "  'boltrig_home': os.environ.get('BOLTRIG_OPENCODE_HOME'),\n"
        "}))\n"
        "print(json.dumps({'type':'message','text':'done'}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    home = tmp_path / "opencode"
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/home/will")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/will/.config")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-user")
    monkeypatch.setenv("RUNPOD_API_KEY", "rpa-user")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("BOLTRIG_OPENCODE_HOME", str(home))

    rt = OpenCodeRuntime(endpoint=_endpoint(), command=str(script))
    res = await rt.run("prompt", _ctx(repo_root=str(tmp_path)), tools=[])

    assert res.ok and not res.degraded
    child = json.loads(env_sink.read_text(encoding="utf-8"))
    assert child == {
        "home": str(home / "home"),
        "config": str(home / "config"),
        "opencode_config": str(home / "config" / "opencode"),
        "openai": None,
        "runpod": None,
        "anthropic": None,
        "boltrig_home": None,
    }
