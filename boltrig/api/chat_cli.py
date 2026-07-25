"""``boltrig chat`` - the user-facing terminal client. A THIN head: it talks
to agents through the stack (the kernel chokepoint), never embedding a runtime.

Modes: the first-party head (default) is PAT-authenticated SSE chat against the
kernel API (``POST /v1/chat``), the full control surface; ``--via-gateway`` is a
messaging surface over the channel gateway's generic JSON-lines adapter (the
frame codec duplicates custom_surface.py's protocol lines, the SEC-28 idiom).

Token order: ``--token`` > ``BOLTRIG_CLI_TOKEN`` > ~/.config/boltrig/cli.toml.
The token is never logged.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tomllib
from collections.abc import AsyncIterator
from typing import Any

import httpx

DEFAULT_SERVER = "http://127.0.0.1:8000"
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "boltrig", "cli.toml"
)
ENV_TOKEN = "BOLTRIG_CLI_TOKEN"
ENV_SERVER = "BOLTRIG_CLI_SERVER"

# A target slug is short, safe-charset routing data (same rule as the kernel's
# channel_routes._clean_target) - checked client-side so a typo fails here.
_TARGET_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")

_HELP = """commands:
  /approve <id>          approve a pending HITL request
  /deny <id>             deny a pending HITL request
  /answer <id> <text>    answer an agent's clarifying question
  /target <slug>         (gateway mode) address the CoS or a named subagent
  /help                  show this help
  /quit                  exit (Ctrl-C / Ctrl-D also exit cleanly)"""


class ChatCliError(Exception):
    """A clean, user-facing failure - printed, never a traceback."""


def load_config(path: str) -> dict[str, Any]:
    """The CLI config file (TOML), or {} when absent; malformed TOML is an
    error, never a silent fall-through to 'no token configured'."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ChatCliError(f"cannot parse {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def resolve_setting(
    flag: str | None, env_value: str | None, config_value: Any,
    default: str | None = None,
) -> str | None:
    """Flag > env > config file > default; the first non-empty string wins."""
    for candidate in (flag, env_value, config_value):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return default


class SseParser:
    """Incremental ``data:``-only SSE parser for /v1/chat; comments and
    malformed / non-object payloads are dropped, never fatal."""

    def __init__(self) -> None:
        self._data: list[str] = []

    def feed(self, line: str) -> dict[str, Any] | None:
        if line == "":
            return self.flush()
        if line.startswith("data:"):
            self._data.append(line[len("data:"):].lstrip(" "))
        return None  # comments / event: / id: fields carry nothing we render

    def flush(self) -> dict[str, Any] | None:
        if not self._data:
            return None
        payload, self._data = "\n".join(self._data), []
        try:
            event = json.loads(payload)
        except ValueError:
            return None
        return event if isinstance(event, dict) else None


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Yield the events of a streaming (httpx) SSE line source as they arrive."""
    parser = SseParser()
    async for line in lines:
        if (event := parser.feed(line)) is not None:
            yield event
    if (event := parser.flush()) is not None:
        yield event


def render_event(event: dict[str, Any]) -> str | None:
    """One event's terminal rendering - a string to write verbatim (deltas
    stream inline), or None (message_start, heartbeat, unknown types)."""
    etype = event.get("type")
    if etype in ("text_delta", "reasoning_delta"):
        return str(event.get("delta", ""))
    if etype == "tool_call":
        tool = event.get("tool") or event.get("verb") or "?"
        keys = (event.get("args_summary") or {}).get("keys") or []
        args = f"({', '.join(str(k) for k in keys)})" if keys else ""
        return f"\n[tool] {tool}{args}\n"
    if etype == "tool_result":
        return f"[tool] -> {event.get('status') or '?'}\n"
    if etype == "hitl":
        rid = event.get("hitl_request_id") or "?"
        kind, question = event.get("kind") or "approval", event.get("question") or ""
        return (f"\n*** HUMAN INPUT NEEDED ({kind}): {question}\n"
                f"*** respond: /approve {rid}  or  /deny {rid}\n")
    if etype == "question":
        qid, prompt = event.get("question_id") or "?", event.get("prompt") or ""
        choices = event.get("choices") or []
        hint = f" (choices: {', '.join(str(c) for c in choices)})" if choices else ""
        return (f"\n*** QUESTION: {prompt}{hint}\n"
                f"*** answer: /answer {qid} <your answer>\n")
    if etype == "subagent":
        name = event.get("name") or event.get("child_run_id") or "?"
        return f"\n[subagent] {name}: {event.get('task') or ''}\n"
    if etype == "cancelled":
        return "\n(cancelled)\n"
    if etype == "message_end":
        return "\n"
    return None


def parse_command(line: str) -> tuple[str, str] | None:
    """``"/approve hitl-1"`` -> ``("approve", "hitl-1")``; chat text -> None.
    The raw remainder keeps its spacing (an answer needs it)."""
    if not line.startswith("/") or line.startswith("//"):
        return None
    name, _, rest = line[1:].partition(" ")
    name = name.strip().lower()
    return (name, rest.strip()) if name else None


def clean_target(value: Any) -> str | None:
    """A target slug or None (the kernel's channel_routes._clean_target rule)."""
    slug = str(value or "").strip()
    return slug if _TARGET_RE.fullmatch(slug) else None


# The gateway frame codec, duplicated from services/channel_gateway/clients/
# custom_surface.py (the SEC-28-sanctioned idiom - never import the severed service).
def encode_frame(sender: str, text: str, message_id: str, target: str | None = None) -> bytes:
    """One inbound JSON-lines frame; the loop uses a per-process monotonic id."""
    frame: dict[str, Any] = {"id": message_id, "sender": sender, "text": text}
    if target:
        frame["target"] = target
    return (json.dumps(frame, separators=(",", ":")) + "\n").encode()


def decode_frame(line: bytes) -> dict[str, Any] | None:
    """One outbound line, or None - a malformed line is dropped, never fatal."""
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return message if isinstance(message, dict) else None


async def stream_turn(
    client: httpx.AsyncClient, server: str, token: str,
    message: str, conversation_id: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """POST one chat turn and yield its SSE events as they arrive."""
    body: dict[str, Any] = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    try:
        async with client.stream(
            "POST", f"{server}/v1/chat", json=body, headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            if resp.status_code != 200:
                raise ChatCliError(_http_error(resp.status_code, await resp.aread()))
            async for event in parse_sse(resp.aiter_lines()):
                yield event
    except httpx.HTTPError as exc:
        raise ChatCliError(
            f"cannot reach the kernel at {server} ({type(exc).__name__}) - "
            "is `boltrig serve` running?"
        ) from exc


async def respond_hitl(
    client: httpx.AsyncClient, server: str, token: str, request_id: str, decision: str
) -> dict[str, Any]:
    """Approve/deny a pending HITL request via /v1/hitl/{id}/respond."""
    return await _post(client, f"{server}/v1/hitl/{request_id}/respond", token,
                       {"decision": decision, "notes": ""})


async def answer_question(
    client: httpx.AsyncClient, server: str, token: str, question_id: str, answer: str
) -> dict[str, Any]:
    """Answer an agent's clarifying question via /v1/hitl/{id}/answer."""
    return await _post(client, f"{server}/v1/hitl/{question_id}/answer", token,
                       {"answer": answer})


async def _post(
    client: httpx.AsyncClient, url: str, token: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise ChatCliError(f"request failed ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise ChatCliError(_http_error(resp.status_code, resp.content))
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _http_error(status: int, body: bytes) -> str:
    """A one-line, user-facing HTTP failure. The token is never part of it."""
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        payload = {}
    reason = payload.get("reason") or payload.get("error") if isinstance(payload, dict) else ""
    if status in (401, 403):
        return (f"authentication failed (HTTP {status}) - check the token "
                "(--token / BOLTRIG_CLI_TOKEN / ~/.config/boltrig/cli.toml)")
    return f"request failed (HTTP {status}){f': {reason}' if reason else ''}"


async def _read_input(prompt: str) -> str | None:
    """One input line off the event loop; None on Ctrl-D."""
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        return None


async def _head_loop(args: Any) -> int:
    config_path = args.config or DEFAULT_CONFIG_PATH
    config = load_config(config_path)
    token = resolve_setting(args.token, os.environ.get(ENV_TOKEN), config.get("token"))
    if token is None:
        print("no token: pass --token, set BOLTRIG_CLI_TOKEN, or add token = \"...\" "
              f"to {config_path} (mint a PAT from your account)", file=sys.stderr)
        return 2
    server = resolve_setting(args.server, os.environ.get(ENV_SERVER),
                             config.get("server"), DEFAULT_SERVER) or DEFAULT_SERVER
    server = server.rstrip("/")
    conversation_id = args.conversation
    print(f"boltrig chat -> {server} (PAT auth). /help for commands, /quit to exit.")
    # No read timeout: heartbeats keep a quiet turn's stream alive server-side.
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
        while True:
            line = await _read_input("> ")
            if line is None:
                break
            text = line.strip()
            if not text:
                continue
            if (command := parse_command(text)) is not None:
                if not await _head_command(client, server, token, command):
                    break
                continue
            try:
                async for event in stream_turn(client, server, token, text,
                                               conversation_id):
                    if event.get("type") == "message_start":
                        conversation_id = event.get("conversation_id") or conversation_id
                    if (chunk := render_event(event)) is not None:
                        print(chunk, end="", flush=True)
            except ChatCliError as exc:
                print(f"\nerror: {exc}", file=sys.stderr)
    print()
    return 0


async def _head_command(
    client: httpx.AsyncClient, server: str, token: str, command: tuple[str, str]
) -> bool:
    """Run one slash command in head mode; False means leave the loop."""
    name, rest = command
    try:
        if name in ("quit", "exit"):
            return False
        if name == "help":
            print(_HELP)
        elif name in ("approve", "deny"):
            if not rest:
                print(f"usage: /{name} <hitl-request-id>")
            else:
                result = await respond_hitl(client, server, token, rest.split()[0], name)
                print(f"({name}: {result.get('status', 'ok')})")
        elif name == "answer":
            qid, _, answer = rest.partition(" ")
            if not qid or not answer.strip():
                print("usage: /answer <question-id> <your answer>")
            else:
                result = await answer_question(client, server, token, qid, answer.strip())
                print(f"(answer: {result.get('status', 'ok')})")
        else:
            print(f"unknown command /{name} - /help for commands")
    except ChatCliError as exc:
        print(f"error: {exc}", file=sys.stderr)
    return True


async def _gateway_loop(args: Any) -> int:
    target = clean_target(args.target) if args.target else None
    if args.target and target is None:
        print(f"bad --target slug: {args.target!r}", file=sys.stderr)
        return 2
    sender = args.sender_id
    try:
        reader, writer = await asyncio.open_connection(
            args.gateway_host, args.gateway_port
        )
    except OSError as exc:
        print(f"cannot reach the channel gateway at "
              f"{args.gateway_host}:{args.gateway_port} ({exc})", file=sys.stderr)
        return 2
    recv = asyncio.create_task(_gateway_recv(reader))
    print(f"boltrig chat -> gateway {args.gateway_host}:{args.gateway_port} "
          f"as {sender!r} (target: {target or 'channel default (cos)'}). "
          "/target <slug> to address, /quit to exit.")
    seq = 0
    try:
        while True:
            line = await _read_input("> ")
            if line is None:
                break
            text = line.strip()
            if not text:
                continue
            if (command := parse_command(text)) is not None:
                name, rest = command
                if name in ("quit", "exit"):
                    break
                if name == "help":
                    print(_HELP)
                elif name == "target":
                    if (new_target := clean_target(rest)) is None:
                        print("usage: /target <slug> (e.g. cos, or a subagent slug)")
                    else:
                        target = new_target
                        print(f"(target: {target})")
                else:
                    print(f"unknown command /{name} - /help for commands")
                continue
            seq += 1
            writer.write(encode_frame(sender, text, f"{sender}-{seq}", target))
            await writer.drain()
    finally:
        recv.cancel()
        writer.close()
    print()
    return 0


async def _gateway_recv(reader: asyncio.StreamReader) -> None:
    """Render outbound notifications as they arrive (see custom_surface.py)."""
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            if (message := decode_frame(line)) is not None:
                print(f"\n<< {message.get('text')}", flush=True)
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


def run(args: Any) -> int:
    """Entry point for the ``chat`` subcommand (dispatched from cli.py)."""
    try:
        if args.via_gateway:
            return asyncio.run(_gateway_loop(args))
        return asyncio.run(_head_loop(args))
    except KeyboardInterrupt:
        print()
        return 0
    except ChatCliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
