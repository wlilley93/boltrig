"""Isolated Chromium executor for fixed, kernel-governed browser verbs.

It listens only on a shared Unix socket.  There is no host port and no raw CDP
or Python endpoint: the public kernel remains the only authority and this
process is only the effect carriage inside the fleet image.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from boltrig.adapters.builtin.browser_cli import BrowserCliAdapter
from boltrig.fleet.browser_egress_proxy import DEFAULT_PROXY_PORT, start_browser_egress_proxy
from boltrig.models import InvocationContext

DEFAULT_SOCKET = "/run/boltrig-browser/browser.sock"
_MAX_REQUEST_BYTES = 32 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9@._:-]{1,200}$")


def create_app(
    adapter: BrowserCliAdapter | None = None,
    *,
    require_live_cdp: bool | None = None,
    manage_egress_proxy: bool | None = None,
) -> FastAPI:
    browser = adapter if adapter is not None else BrowserCliAdapter(executor_socket="")
    check_cdp = adapter is None if require_live_cdp is None else require_live_cdp
    manage_proxy = adapter is None if manage_egress_proxy is None else manage_egress_proxy
    proxy_state = {"serving": not manage_proxy}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        server = None
        if manage_proxy:
            server = await start_browser_egress_proxy(port=_proxy_port())
            proxy_state["serving"] = server.is_serving()
        try:
            yield
        finally:
            proxy_state["serving"] = False
            if server is not None:
                server.close()
                await server.wait_closed()

    allowed = frozenset(spec.verb_id for spec in browser.describe())
    app = FastAPI(
        title="Boltrig browser executor",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> JSONResponse:
        status = await browser.health()
        if status == "ok" and check_cdp:
            from boltrig.fleet.stack_tool_health import _probe_browser_cdp

            status = "ok" if await _probe_browser_cdp(1.0) else "down"
        if status == "ok" and not proxy_state["serving"]:
            status = "down"
        return JSONResponse({"status": status}, status_code=200 if status == "ok" else 503)

    @app.post("/v1/execute")
    async def execute(request: Request) -> JSONResponse:
        if request.headers.get("x-boltrig-browser-protocol") != "1":
            return _refusal(403, "browser protocol refused")
        raw = await _bounded_body(request)
        if raw is None:
            return _refusal(413, "browser request is too large")
        try:
            document = json.loads(raw)
            verb, params, context = _request_parts(document, allowed)
        except (UnicodeDecodeError, ValueError):
            return _refusal(400, "invalid browser request")
        result = await browser.execute(verb, params, None, context)
        if result.ok:
            return JSONResponse({"ok": True, "output": result.output})
        error = result.error
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "class": error.error_class.value if error else "internal",
                    "message": (error.message if error else "browser executor failed")[:240],
                    "retryable": bool(error and error.retryable),
                },
            }
        )

    return app


async def _bounded_body(request: Request) -> bytes | None:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_REQUEST_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _request_parts(
    document: Any, allowed: frozenset[str]
) -> tuple[str, dict[str, Any], InvocationContext]:
    if not isinstance(document, dict) or set(document) != {"verb", "params", "context"}:
        raise ValueError("invalid request")
    verb = document.get("verb")
    params = document.get("params")
    raw_context = document.get("context")
    if not isinstance(verb, str) or verb not in allowed or not isinstance(params, dict):
        raise ValueError("invalid request")
    if not isinstance(raw_context, dict) or set(raw_context) != {"tenant_id", "owner_id"}:
        raise ValueError("invalid context")
    tenant = _identity(raw_context.get("tenant_id"))
    owner = _identity(raw_context.get("owner_id"))
    return verb, params, InvocationContext(tenant_id=tenant, actor=owner)


def _identity(value: Any) -> str:
    identity = str(value or "")
    if not _IDENTITY.fullmatch(identity):
        raise ValueError("invalid identity")
    return identity


def _refusal(status: int, reason: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"class": "invalid", "message": reason}}, status_code=status
    )


def _socket_path() -> Path:
    raw = (os.environ.get("BOLTRIG_BROWSER_EXECUTOR_SOCKET") or DEFAULT_SOCKET).strip()
    path = Path(raw)
    if not path.is_absolute() or len(raw) > 240:
        raise RuntimeError("browser executor socket must be a bounded absolute path")
    return path


def _proxy_port() -> int:
    raw = str(os.environ.get("BOLTRIG_BROWSER_PROXY_PORT") or DEFAULT_PROXY_PORT).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("browser proxy port is invalid") from exc
    if port < 1 or port > 65535:
        raise RuntimeError("browser proxy port is invalid")
    return port


def _prepare_socket(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(details.st_mode) or details.st_uid != os.getuid():
        raise RuntimeError("refusing to replace non-owned browser executor path")
    path.unlink()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = _socket_path()
    if args == ["--health"]:
        from boltrig.adapters.builtin.browser_executor_client import executor_health

        return 0 if asyncio.run(executor_health(str(path), timeout=2.0)) == "ok" else 1
    if args:
        raise SystemExit("usage: python -m boltrig.fleet.browser_executor [--health]")
    _prepare_socket(path)
    os.umask(0o007)
    uvicorn.run(create_app(), uds=str(path), log_level="info", access_log=False)
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
