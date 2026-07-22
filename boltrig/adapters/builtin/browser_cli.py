"""Browser Use CLI automation as governed Boltrig verbs.

The external CLI is powerful because it executes Python against a browser
session. This adapter keeps the default surface narrow: health/auth checks,
opening a public HTTP(S) URL, page info, and explicit remote daemon start/stop.
Arbitrary Python is intentionally not exposed as a verb.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.adapters.builtin.script_base import (
    base_env,
    json_or_text as _json_or_text,
    run_process,
    schema as _schema,
)
from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed
from boltrig.models import InvocationContext

CommandRunner = Callable[
    [list[str], str | None, dict[str, str]],
    Awaitable[tuple[int, str, str]],
]

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_HOME = "/var/lib/boltrig/browser-cli"
_PRIVATE_HOSTS = {"localhost", "localhost.localdomain"}
_CLOUD_POLICY_STACK = {"stack", "stack-owned", "stack_owned"}
_CLOUD_POLICY_DISABLED = {"", "0", "false", "no", "off", "disabled", "none"}
_STACK_CLOUD_ENV = {
    "BOLTRIG_BROWSER_CLOUD_API_KEY": ("BROWSER_USE_API_KEY", "BROWSER_USE_CLOUD_API_KEY"),
    "BOLTRIG_BROWSER_CLOUD_PROFILE_ID": ("BROWSER_USE_PROFILE_ID",),
    "BOLTRIG_BROWSER_CLOUD_PROJECT_ID": ("BROWSER_USE_PROJECT_ID",),
    "BOLTRIG_BROWSER_CLOUD_TEAM_ID": ("BROWSER_USE_TEAM_ID",),
}


def _csv(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in (value or "").split(",") if item.strip())


class BrowserCliAdapter:
    id = "browser-cli"
    version = "0.1.0"
    runtime = "script"
    source = "builtin"

    def __init__(
        self,
        *,
        bin_path: str | None = None,
        command_runner: CommandRunner | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        allowed_domains: tuple[str, ...] | None = None,
    ) -> None:
        self.bin_path = bin_path or os.environ.get("BOLTRIG_BROWSER_CLI_BIN") or "browser-use"
        self._runner = command_runner
        self.timeout = timeout
        self.allowed_domains = allowed_domains or _csv(os.environ.get("BOLTRIG_BROWSER_ALLOWED_DOMAINS"))

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        name = {"type": "string", "minLength": 1}
        return [
            VerbSpec("browser.doctor", "browser",
                     _schema(), any_out, "low", "Run Browser Use CLI diagnostics."),
            VerbSpec("browser.auth.status", "browser",
                     _schema(), any_out, "low", "Read Browser Use auth status."),
            VerbSpec("browser.page.info", "browser",
                     _schema(props={"name": name}), any_out, "low",
                     "Read information about the active browser page."),
            VerbSpec("browser.tab.open", "browser",
                     _schema(["url"], {"url": {"type": "string"}, "name": name}),
                     any_out, "high", "Open a public HTTP(S) URL in a browser tab."),
            VerbSpec("browser.remote.start", "browser",
                     _schema(["name"], {"name": name}), any_out, "high",
                     "Start a named Browser Use remote daemon."),
            VerbSpec("browser.remote.stop", "browser",
                     _schema(["name"], {"name": name}), any_out, "high",
                     "Stop a named Browser Use remote daemon."),
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential, context
        try:
            argv, stdin, env = self._command(verb, params)
        except ValueError as exc:
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
        code, stdout, _stderr = await self._run(argv, stdin, env)
        if code != 0:
            # Fixed message: child stderr is attacker-influenceable output and
            # is never echoed into a Result (it could carry secrets or UI
            # red herrings); only the exit code is reported.
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    f"browser CLI exited {code}",
                    retryable=True,
                )
            )
        return Result.success({
            "command": _safe_command(argv),
            "result": _json_or_text(stdout),
        })

    async def health(self) -> str:
        code, _, _ = await self._run([self.bin_path, "--doctor"], None, {})
        if code == 127:
            # The binary is not co-located with this process (it executes in the
            # fleet worker); absence here is unknown, not down - the fleet
            # heartbeat is the live proof path for this tool.
            return "unknown"
        return "ok" if code == 0 else "down"

    def _command(
        self, verb: str, params: dict[str, Any]
    ) -> tuple[list[str], str | None, dict[str, str]]:
        if verb == "browser.doctor":
            return [self.bin_path, "--doctor"], None, {}
        if verb == "browser.auth.status":
            return [self.bin_path, "auth", "status"], None, {}
        if verb == "browser.page.info":
            return [self.bin_path], _page_info_script(), _name_env(params)
        if verb == "browser.tab.open":
            url = _validate_url(str(params.get("url") or ""), self.allowed_domains)
            return [self.bin_path], _open_script(url), _name_env(params)
        if verb == "browser.remote.start":
            name = _clean_name(params.get("name"))
            return [self.bin_path], f"start_remote_daemon({json.dumps(name)})\n", {}
        if verb == "browser.remote.stop":
            name = _clean_name(params.get("name"))
            return [self.bin_path], f"stop_remote_daemon({json.dumps(name)})\n", {}
        raise ValueError(f"unknown verb {verb}")

    async def _run(
        self, argv: list[str], stdin: str | None, extra_env: dict[str, str]
    ) -> tuple[int, str, str]:
        if self._runner is not None:
            return await self._runner(argv, stdin, extra_env)
        return await run_process(
            argv,
            stdin=stdin,
            env=_process_env(extra_env),
            timeout=self.timeout,
            missing="browser-use command not found",
            timed_out="browser-use command timed out",
        )


def _process_env(extra_env: dict[str, str]) -> dict[str, str]:
    root = Path(os.environ.get("BOLTRIG_BROWSER_CLI_HOME") or _DEFAULT_HOME)
    env = base_env() | {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
    }
    env.update(_stack_cloud_env(os.environ))
    env.update(extra_env)
    return env


def _stack_cloud_env(source: Mapping[str, str]) -> dict[str, str]:
    policy = (source.get("BOLTRIG_BROWSER_CLOUD_POLICY") or "disabled").strip().lower()
    if policy in _CLOUD_POLICY_DISABLED:
        return {}
    if policy not in _CLOUD_POLICY_STACK:
        return {}
    out = {"BROWSER_USE_CLOUD": "true"}
    for source_key, child_keys in _STACK_CLOUD_ENV.items():
        value = (source.get(source_key) or "").strip()
        if not value:
            continue
        for child_key in child_keys:
            out[child_key] = value
    return out


def _page_info_script() -> str:
    return "import json\nprint(json.dumps(page_info(), default=str))\n"


def _open_script(url: str) -> str:
    return (
        "import json\n"
        f"new_tab({json.dumps(url)})\n"
        "print(json.dumps(page_info(), default=str))\n"
    )


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("name is required")
    if any(ch.isspace() for ch in name):
        raise ValueError("name must not contain whitespace")
    return name


def _name_env(params: dict[str, Any]) -> dict[str, str]:
    if not params.get("name"):
        return {}
    return {"BU_NAME": _clean_name(params["name"])}


def _validate_url(raw: str, allowed_domains: tuple[str, ...]) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be public http(s)")
    host = parsed.hostname.lower().rstrip(".")
    if host in _PRIVATE_HOSTS or host.endswith(".localhost"):
        raise ValueError("localhost browser navigation is not allowed")
    try:
        # The shared egress guard (INJ-02/SEC-61): refuses unspecified /
        # multicast / link-local / reserved literal IPs AND any hostname that
        # resolves to internal space - a hand-rolled literal-IP check misses
        # both (e.g. http://0.0.0.0/).
        assert_egress_allowed(raw)
    except EgressBlocked as exc:
        raise ValueError(str(exc)) from exc
    if allowed_domains and not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        raise ValueError("domain is not allowed for browser navigation")
    return raw


def _safe_command(argv: list[str]) -> list[str]:
    return argv[1:] if argv else []


def build() -> BrowserCliAdapter:
    return BrowserCliAdapter()
