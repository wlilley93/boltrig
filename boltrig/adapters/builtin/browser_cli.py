"""Browser Use automation exposed only as fixed kernel-governed verbs.

Arbitrary Python and caller-selected CDP are intentionally absent. Visual
actions are tied to the exact owner-scoped frame the caller displayed; the
isolated executor rechecks that frame before performing an effect.
"""

from __future__ import annotations

import base64
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    McpResourceSpec,
    Result,
    VerbSpec,
)
from boltrig.adapters.builtin.browser_commands import (
    build_command,
    clean_executor_socket,
    csv,
    process_env,
    safe_command,
    session_name,
)
from boltrig.adapters.builtin.browser_contract import (
    DEFAULT_TIMEOUT,
    MAX_AX_NODES,
    browser_verb_specs,
)
from boltrig.adapters.builtin.browser_frames import (
    BrowserFrame,
    BrowserFrameStore,
    bounded_int,
    frame_scope,
    load_frame,
    owner_id,
    project_ax_node,
    project_cursor,
    safe_text,
)
from boltrig.adapters.builtin.script_base import json_or_text, run_process
from boltrig.models import InvocationContext

CommandRunner = Callable[
    [list[str], str | None, dict[str, str]],
    Awaitable[tuple[int, str, str]],
]


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
        timeout: float = DEFAULT_TIMEOUT,
        allowed_domains: tuple[str, ...] | None = None,
        executor_socket: str | None = None,
    ) -> None:
        self.bin_path = bin_path or os.environ.get("BOLTRIG_BROWSER_CLI_BIN") or "browser-use"
        self._runner = command_runner
        self.timeout = timeout
        self.allowed_domains = allowed_domains or csv(
            os.environ.get("BOLTRIG_BROWSER_ALLOWED_DOMAINS")
        )
        configured_socket = os.environ.get("BOLTRIG_BROWSER_EXECUTOR_SOCKET")
        self.executor_socket = clean_executor_socket(
            configured_socket if executor_socket is None else executor_socket
        )
        self._frame_store = BrowserFrameStore()

    def describe(self) -> list[VerbSpec]:
        return browser_verb_specs()

    def mcp_resources(self) -> list[McpResourceSpec]:
        return [
            McpResourceSpec(
                uri_prefix="browser-frame://",
                list_verb="browser.frames.list",
                read_verb="browser.frame.read",
                collection_key="frames",
                id_key="id",
                name_key="title",
                description_key="url",
                read_id_param="id",
                blob_key="data",
                media_type_key="media_type",
            )
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del credential
        if self.executor_socket:
            from boltrig.adapters.builtin.browser_executor_client import execute_over_socket

            return await execute_over_socket(
                self.executor_socket, verb, params, context, timeout=self.timeout
            )
        try:
            local = self._local_result(verb, params, context)
            if local is not None:
                return Result.success(local)
            return await self._execute_cli(verb, params, context)
        except LookupError as exc:
            return Result.failure(AdapterError(ErrorClass.NOT_FOUND, str(exc)))
        except ValueError as exc:
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
        except Exception as exc:  # adapters must not crash the dispatcher
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"browser adapter error: {type(exc).__name__}")
            )

    async def _execute_cli(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> Result:
        expected = self._expected_frame(verb, params, context)
        with tempfile.TemporaryDirectory(prefix="boltrig-browser-") as temp_dir:
            frame_path = str(Path(temp_dir) / "frame.jpg")
            argv, stdin, env = self._command(
                verb,
                params,
                frame_path=frame_path,
                expected_digest=expected.digest if expected is not None else None,
            )
            code, stdout, _stderr = await self._run(argv, stdin, env)
            if code != 0:
                return Result.failure(
                    AdapterError(
                        ErrorClass.UNAVAILABLE,
                        f"browser CLI exited {code}",
                        retryable=True,
                    )
                )
            parsed = json_or_text(stdout)
            return Result.success(
                self._project_result(
                    verb,
                    parsed,
                    frame_path=frame_path,
                    params=params,
                    context=context,
                )
            )

    async def health(self) -> str:
        if self.executor_socket:
            from boltrig.adapters.builtin.browser_executor_client import executor_health

            return await executor_health(self.executor_socket, timeout=min(self.timeout, 3.0))
        code, _, _ = await self._run([self.bin_path, "--doctor"], None, {})
        if code == 127:
            return "unknown"
        return "ok" if code == 0 else "down"

    def _command(
        self,
        verb: str,
        params: dict[str, Any],
        *,
        frame_path: str | None = None,
        expected_digest: str | None = None,
    ) -> tuple[list[str], str | None, dict[str, str]]:
        return build_command(
            self.bin_path,
            verb,
            params,
            allowed_domains=self.allowed_domains,
            frame_path=frame_path,
            expected_digest=expected_digest,
        )

    def _local_result(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> dict[str, Any] | None:
        if verb == "browser.frames.list":
            limit = bounded_int(params.get("limit", 100), minimum=1, maximum=100, name="limit")
            return {
                "frames": self._frame_store.list(frame_scope(context, session_name(params)), limit)
            }
        if verb == "browser.frame.read":
            frame = self._frame_store.owned(params.get("id"), context)
            return {
                "id": frame.id,
                "media_type": "image/jpeg",
                "data": base64.b64encode(frame.data).decode("ascii"),
            }
        return None

    def _expected_frame(
        self, verb: str, params: dict[str, Any], context: InvocationContext
    ) -> BrowserFrame | None:
        if verb not in {"browser.click", "browser.type", "browser.scroll", "browser.key.press"}:
            return None
        frame = self._frame_store.owned(params.get("expected_frame_id"), context)
        if frame.session_name != session_name(params):
            raise ValueError("expected frame belongs to another browser session")
        return frame

    def _project_result(
        self,
        verb: str,
        parsed: Any,
        *,
        frame_path: str,
        params: dict[str, Any],
        context: InvocationContext,
    ) -> dict[str, Any]:
        legacy = self._project_legacy(verb, parsed, params)
        if legacy is not None:
            return legacy
        if verb == "browser.tabs.list":
            return {"tabs": _project_tabs(parsed)}
        if verb == "browser.inspect":
            raw_rows = parsed.get("nodes") if isinstance(parsed, dict) else []
            rows = raw_rows if isinstance(raw_rows, list) else []
            nodes = [project_ax_node(row) for row in rows[:MAX_AX_NODES] if isinstance(row, dict)]
            return {"nodes": [row for row in nodes if row is not None]}
        if verb not in _FRAME_VERBS or not isinstance(parsed, dict):
            raise ValueError("browser CLI returned an invalid result")
        status = str(parsed.get("status") or "")
        if status not in {"ok", "stale_frame"}:
            raise ValueError("browser CLI returned an invalid action status")
        frame = load_frame(
            frame_path,
            parsed.get("page"),
            tenant_id=str(context.tenant_id),
            owner_id_value=owner_id(context),
            session_name=session_name(params),
        )
        self._frame_store.remember(frame)
        output: dict[str, Any] = {"status": status, "frame": frame.view()}
        if isinstance(parsed.get("cursor"), dict):
            output["cursor"] = project_cursor(parsed["cursor"])
        return output

    def _project_legacy(
        self, verb: str, parsed: Any, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        if verb not in _LEGACY_VERBS:
            return None
        argv, _stdin, _env = self._command(verb, params)
        result = parsed if isinstance(parsed, dict) else {"value": parsed}
        return {"command": safe_command(argv), "result": result}

    async def _run(
        self, argv: list[str], stdin: str | None, extra_env: dict[str, str]
    ) -> tuple[int, str, str]:
        if self._runner is not None:
            return await self._runner(argv, stdin, extra_env)
        return await run_process(
            argv,
            stdin=stdin,
            env=process_env(extra_env),
            timeout=self.timeout,
            missing="browser-use command not found",
            timed_out="browser-use command timed out",
        )


_LEGACY_VERBS = frozenset(
    {
        "browser.doctor",
        "browser.auth.status",
        "browser.page.info",
        "browser.tab.open",
        "browser.remote.start",
        "browser.remote.stop",
    }
)
_FRAME_VERBS = frozenset(
    {
        "browser.navigate",
        "browser.tab.select",
        "browser.tab.close",
        "browser.snapshot",
        "browser.click",
        "browser.type",
        "browser.scroll",
        "browser.key.press",
    }
)


def _project_tabs(parsed: Any) -> list[dict[str, str]]:
    rows = parsed.get("value") if isinstance(parsed, dict) else []
    rows = rows if isinstance(rows, list) else []
    tabs: list[dict[str, str]] = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        target_id = str(row.get("target_id") or row.get("targetId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", target_id):
            continue
        tabs.append(
            {
                "id": target_id,
                "title": safe_text(row.get("title"), 512),
                "url": safe_text(row.get("url"), 4096),
            }
        )
    return tabs


def build() -> BrowserCliAdapter:
    return BrowserCliAdapter()
