"""OpenCode runtime seam for coding agents.

This is deliberately a CLI/runtime wrapper, not a kernel side door. OpenCode may
edit files inside its configured working directory, but any Boltrig verb/tool it
uses still needs to come back through the kernel's normal MCP/adapter paths.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boltrig.models import InvocationContext

from .result import AgentResult

_DEFAULT_TIMEOUT = 600.0
_MAX_STDIO = 16_000
_DEFAULT_HOME = "/var/lib/boltrig/opencode"
_BASE_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)

# issue_token(tenant_id, grants, *, run_id, actor, skills, workspace_id) -> token
TokenIssuer = Callable[..., str]


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded(value: str, limit: int = _MAX_STDIO) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _redact(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _stack_env(root: str | None = None) -> dict[str, str]:
    base = Path(root or _DEFAULT_HOME).expanduser()
    return {
        "HOME": str(base / "home"),
        "XDG_CONFIG_HOME": str(base / "config"),
        "XDG_DATA_HOME": str(base / "data"),
        "XDG_STATE_HOME": str(base / "state"),
        "OPENCODE_CONFIG_DIR": str(base / "config" / "opencode"),
    }


def _process_env(extra_env: dict[str, str]) -> dict[str, str]:
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if os.environ.get(key)}
    env.update(extra_env)
    return env


def _json_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _dig_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_dig_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "delta", "summary"):
        found = _dig_text(value.get(key))
        if found:
            return found
    msg = value.get("message")
    if isinstance(msg, dict):
        return _dig_text(msg)
    return ""


def _summary(events: list[dict[str, Any]], stdout: str, stderr: str) -> str:
    for event in reversed(events):
        text = _dig_text(event).strip()
        if text:
            return text[:256]
    for raw in (stdout, stderr):
        line = raw.strip().splitlines()[-1:] or []
        if line:
            return line[0][:256]
    return "opencode run completed"


def _usage(events: list[dict[str, Any]]) -> tuple[int, int]:
    tokens = 0
    cost = 0
    for event in events:
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else event
        tokens = int(
            usage.get("total_tokens")
            or usage.get("tokens_used")
            or usage.get("tokens")
            or tokens
            or 0
        )
        cost = int(usage.get("cost_micros") or cost or 0)
    return tokens, cost


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except Exception:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                return
            await proc.wait()


@dataclass(frozen=True)
class OpenCodeCommand:
    """The argv/env/cwd shape sent to OpenCode; split out for tests."""

    argv: list[str]
    cwd: str | None
    env: dict[str, str]
    secrets: tuple[str, ...] = ()
    revoke_token: str | None = None


class OpenCodeRuntime:
    """Run one agent through ``opencode run --format json``.

    ``endpoint.model`` is the authoritative OpenCode model id in provider/model
    form. ``endpoint.base_url`` is treated as the optional ``--attach`` server
    URL, so a warm ``opencode serve`` sidecar can be reused without teaching
    Boltrig about OpenCode internals.
    """

    runtime = "opencode"

    def __init__(
        self,
        *,
        endpoint: Any = None,
        cost_tier: str = "standard",
        command: str | None = None,
        attach_url: str | None = None,
        mcp_url: str | None = None,
        issue_token: TokenIssuer | None = None,
        revoke_token: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.cost_tier = cost_tier
        self.command = command or os.environ.get("BOLTRIG_OPENCODE_BIN") or "opencode"
        self.attach_url = attach_url or os.environ.get("BOLTRIG_OPENCODE_ATTACH")
        self.mcp_url = (
            mcp_url
            or os.environ.get("BOLTRIG_OPENCODE_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
        )
        self._issue = issue_token
        self._revoke = revoke_token
        self.timeout = timeout or float(
            os.environ.get("BOLTRIG_OPENCODE_TIMEOUT_SECONDS") or _DEFAULT_TIMEOUT
        )

    def _mcp_env(self, context: InvocationContext) -> tuple[dict[str, str], str | None]:
        extra = dict(context.extra or {})
        mcp_url = extra.get("opencode_mcp_url") or self.mcp_url
        if not mcp_url:
            return {}, None
        if self._issue is None:
            raise ValueError("mcp_token_unavailable")
        token = self._issue(
            context.tenant_id,
            context.grants,
            run_id=context.run_id,
            actor=context.actor,
            skills=context.skills_loaded,
            workspace_id=context.workspace_id,
            on_behalf_of=context.on_behalf_of,
            extra=dict(context.extra),
        )
        return {
            "BOLTRIG_MCP_URL": str(mcp_url),
            "BOLTRIG_MCP_TOKEN": token,
            "BOLTRIG_MCP_SERVER_NAME": "boltrig-kernel",
        }, token

    def build_command(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> OpenCodeCommand:
        model = getattr(self.endpoint, "model", None)
        if not model:
            raise ValueError("no_model_endpoint")

        extra = dict(context.extra or {})
        repo_root = extra.get("repo_root") or os.environ.get("BOLTRIG_OPENCODE_DIR")
        if repo_root:
            repo_root = str(Path(str(repo_root)).expanduser())
        attach = self.attach_url or getattr(self.endpoint, "base_url", None)
        title = extra.get("opencode_title") or f"{context.actor}:{context.run_id or 'run'}"
        agent = extra.get("opencode_agent")

        argv = [self.command, "run", "--format", "json", "--model", str(model)]
        if attach:
            argv += ["--attach", str(attach)]
        if repo_root:
            argv += ["--dir", str(repo_root)]
        if agent:
            argv += ["--agent", str(agent)]
        if title:
            argv += ["--title", str(title)[:120]]
        if _truthy(extra.get("opencode_auto") or os.environ.get("BOLTRIG_OPENCODE_AUTO")):
            argv.append("--auto")
        argv.append(prompt)
        env = _stack_env(os.environ.get("BOLTRIG_OPENCODE_HOME"))
        mcp_env, token = self._mcp_env(context)
        env.update(mcp_env)
        return OpenCodeCommand(
            argv=argv,
            cwd=repo_root,
            env=env,
            secrets=(token,) if token else (),
            revoke_token=token,
        )

    async def run(
        self, prompt: str, context: InvocationContext, *, tools: list[str]
    ) -> AgentResult:
        command: OpenCodeCommand | None = None
        try:
            command = self.build_command(prompt, context, tools=tools)
        except ValueError as exc:
            return AgentResult.degrade(
                runtime=self.runtime, reason=str(exc), prompt=prompt
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=command.cwd,
                env=_process_env(command.env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except FileNotFoundError:
            return AgentResult.degrade(
                runtime=self.runtime, reason="opencode_unavailable", prompt=prompt
            )
        except TimeoutError:
            await _terminate(proc)
            return AgentResult.degrade(
                runtime=self.runtime, reason="timeout", prompt=prompt
            )
        except Exception as exc:
            return AgentResult.degrade(
                runtime=self.runtime, reason=type(exc).__name__, prompt=prompt
            )
        finally:
            if command and command.revoke_token and self._revoke is not None:
                try:
                    self._revoke(command.revoke_token)
                except Exception:
                    pass

        stdout = _redact(stdout_b.decode("utf-8", errors="replace"), command.secrets)
        stderr = _redact(stderr_b.decode("utf-8", errors="replace"), command.secrets)
        events = _json_events(stdout)
        if proc.returncode != 0:
            return AgentResult.degrade(
                runtime=self.runtime,
                reason=f"exit_{proc.returncode}",
                prompt=prompt,
                summary=_summary(events, stdout, stderr),
            )

        tokens, cost = _usage(events)
        return AgentResult.succeeded(
            output={
                "runtime": self.runtime,
                "event_count": len(events),
                "events_tail": events[-50:],
                "stdout_tail": _bounded(stdout),
                "stderr_tail": _bounded(stderr),
                "mcp_scoped": bool(command.revoke_token),
            },
            summary=_summary(events, stdout, stderr),
            tokens_used=tokens,
            cost_micros=cost,
        )
