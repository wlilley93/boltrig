"""Herdr terminal workspace control as governed Boltrig verbs.

The adapter shells out to the Herdr CLI/socket API. It never receives secrets and
it never bypasses the kernel: callers still need grants for each Herdr verb and
mutating pane/tab operations are audited like any other tool call.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.adapters.builtin.script_base import (
    base_env,
    json_or_text as _json_or_text,
    run_process,
    schema as _schema,
)
from boltrig.models import InvocationContext

CommandRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]

_DEFAULT_HOME = "/var/lib/boltrig/herdr"


def _stack_env(root: str | None = None) -> dict[str, str]:
    base = Path(root or _DEFAULT_HOME).expanduser()
    return {
        "HOME": str(base / "home"),
        "XDG_CONFIG_HOME": str(base / "config"),
        "XDG_DATA_HOME": str(base / "data"),
        "XDG_STATE_HOME": str(base / "state"),
        "HERDR_CONFIG_PATH": str(base / "config" / "config.toml"),
    }


def _process_env(root: str | None = None) -> dict[str, str]:
    env = base_env()
    env.update(_stack_env(root))
    return env


class HerdrAdapter:
    id = "herdr"
    version = "0.1.0"
    runtime = "script"
    source = "builtin"

    def __init__(
        self,
        *,
        bin_path: str | None = None,
        command_runner: CommandRunner | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.bin_path = bin_path or os.environ.get("HERDR_BIN") or "herdr"
        self._runner = command_runner
        self.timeout = timeout
        self._stack_home = os.environ.get("BOLTRIG_HERDR_HOME")

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        return [
            VerbSpec("herdr.snapshot", "herdr", _schema(), any_out, "low",
                     "Read the current Herdr socket snapshot."),
            VerbSpec("herdr.pane.list", "herdr",
                     _schema(props={"workspace": {"type": "string"}}), any_out, "low",
                     "List Herdr panes."),
            VerbSpec("herdr.pane.read", "herdr",
                     _schema(["pane_id"], {"pane_id": {"type": "string"},
                                           "lines": {"type": "integer"},
                                           "source": {"type": "string"}}), any_out, "low",
                     "Read visible or recent pane output."),
            VerbSpec("herdr.tab.create", "herdr",
                     _schema(props={"workspace": {"type": "string"},
                                    "cwd": {"type": "string"},
                                    "label": {"type": "string"},
                                    "focus": {"type": "boolean"}}), any_out, "high",
                     "Create a Herdr tab."),
            VerbSpec("herdr.pane.split", "herdr",
                     _schema(["direction"], {"pane_id": {"type": "string"},
                                             "direction": {"enum": ["right", "down"]},
                                             "ratio": {"type": "number"},
                                             "cwd": {"type": "string"},
                                             "focus": {"type": "boolean"}}), any_out, "high",
                     "Split a Herdr pane."),
            VerbSpec("herdr.pane.run", "herdr",
                     _schema(["pane_id", "command"], {"pane_id": {"type": "string"},
                                                      "command": {"type": "string"}}),
                     any_out, "high", "Run a command in a Herdr pane."),
        ]

    async def execute(
        self, verb: str, params: dict[str, Any], credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential, context
        try:
            argv = self._argv(verb, params)
        except ValueError as exc:
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
        code, stdout, _stderr = await self._run(argv)
        if code != 0:
            # Fixed message: child stderr is never echoed into a Result (it
            # could carry secrets); only the exit code is reported.
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, f"herdr exited {code}",
                             retryable=True)
            )
        return Result.success({"command": argv[1:], "result": _json_or_text(stdout)})

    async def health(self) -> str:
        code, _, _ = await self._run([self.bin_path, "status", "server"])
        return "ok" if code == 0 else "down"

    def _argv(self, verb: str, params: dict[str, Any]) -> list[str]:
        if verb == "herdr.snapshot":
            return [self.bin_path, "api", "snapshot"]
        if verb == "herdr.pane.list":
            argv = [self.bin_path, "pane", "list"]
            if params.get("workspace"):
                argv += ["--workspace", str(params["workspace"])]
            return argv
        if verb == "herdr.pane.read":
            argv = [self.bin_path, "pane", "read", str(params["pane_id"])]
            if params.get("source"):
                argv += ["--source", str(params["source"])]
            if params.get("lines") is not None:
                argv += ["--lines", str(int(params["lines"]))]
            return argv
        if verb == "herdr.tab.create":
            argv = [self.bin_path, "tab", "create"]
            for key, flag in (("workspace", "--workspace"), ("cwd", "--cwd"), ("label", "--label")):
                if params.get(key):
                    argv += [flag, str(params[key])]
            argv.append("--focus" if params.get("focus") else "--no-focus")
            return argv
        if verb == "herdr.pane.split":
            argv = [self.bin_path, "pane", "split"]
            if params.get("pane_id"):
                argv.append(str(params["pane_id"]))
            argv += ["--direction", str(params["direction"])]
            if params.get("ratio") is not None:
                argv += ["--ratio", str(float(params["ratio"]))]
            if params.get("cwd"):
                argv += ["--cwd", str(params["cwd"])]
            argv.append("--focus" if params.get("focus") else "--no-focus")
            return argv
        if verb == "herdr.pane.run":
            return [self.bin_path, "pane", "run", str(params["pane_id"]), str(params["command"])]
        raise ValueError(f"unknown verb {verb}")

    async def _run(self, argv: list[str]) -> tuple[int, str, str]:
        if self._runner is not None:
            return await self._runner(argv)
        return await run_process(
            argv,
            env=_process_env(self._stack_home),
            timeout=self.timeout,
            missing="herdr command not found",
            timed_out="herdr command timed out",
        )


def build() -> HerdrAdapter:
    return HerdrAdapter()
