"""Deterministic OpenAPI -> adapter generator (US-ADP-01, SEC-22).

Given an OpenAPI document (a dict, a URL, a file path, or raw JSON/YAML text)
this builds a working :class:`HttpAdapter` subclass instance. The "AI" step is
the spec -> code transform and it is fully DETERMINISTIC and offline: NO LLM is
called. From every operation in the document we derive:

  * a verb id (``operationId``, synthesised from method + path if absent),
  * a noun id (first tag, else the verb prefix, else the first path segment),
  * an input JSON schema (path + query + header parameters merged with the JSON
    ``requestBody`` schema under a ``body`` property),
  * an output JSON schema (the success response's JSON schema),
  * a consequence (GET is low; mutating verbs are high),
  * a recommended rate limit (from ``x-ratelimit`` / ``x-rate-limit`` extensions
    where present, else a safe default).

The generated adapter carries all of: typed per-verb handlers (one closure per
operation, built from the derived operation table), rate-limit config, error
mapping + retry/backoff (inherited from :class:`HttpAdapter`), and pagination
handling (link- or offset-style, detected from the response schema / query
params). A reviewable source artefact is available via
:meth:`GeneratedAdapter.render_source`.

Review gate (SEC-22). A generated adapter is INERT until a human reviews it:
``activated`` starts ``False`` and :meth:`GeneratedAdapter.review_and_activate`
must be called with a reviewer id to flip it. The registry MUST NOT create verb
bindings for an unactivated adapter; as defence in depth :meth:`execute` itself
refuses to dispatch while inert (returns UNAVAILABLE).
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nankle.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from nankle.adapters.http_base import Handler, HttpAdapter, RateLimitConfig, RetryPolicy
from nankle.models import InvocationContext, utcnow

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_MUTATING = ("post", "put", "patch", "delete")
_ITEMS_KEYS = ("value", "items", "results", "data", "records")
_NEXT_KEYS = ("@odata.nextLink", "nextLink", "next", "next_cursor", "nextPageToken")
_OFFSET_PARAMS = ("startat", "offset", "page", "cursor")


@dataclass(frozen=True)
class _Operation:
    """The derived, deterministic description of one OpenAPI operation."""

    verb_id: str
    noun_id: str
    method: str
    path: str  # template with {param} placeholders
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    header_params: tuple[str, ...]
    has_body: bool
    consequence: str
    pagination: str | None  # 'link' | 'offset' | None
    items_key: str
    next_key: str


@dataclass
class ReviewGate:
    """Human-in-the-loop activation gate for a generated adapter (SEC-22).

    A generated adapter stays inert until a NAMED reviewer activates it. The
    registry consults ``activated`` before creating any binding.
    """

    activated: bool = False
    reviewer: str | None = None
    reviewed_at: datetime | None = None

    def activate(self, reviewer: str) -> None:
        if not reviewer:
            raise ValueError("a reviewer id is required to activate a generated adapter")
        self.activated = True
        self.reviewer = reviewer
        self.reviewed_at = utcnow()


class GeneratedAdapter(HttpAdapter):
    """An :class:`HttpAdapter` whose verbs were derived from an OpenAPI document.

    Inert until :meth:`review_and_activate` is called (SEC-22).
    """

    version = "1.0.0-generated"

    def __init__(
        self,
        *,
        adapter_id: str,
        base_url: str,
        operations: dict[str, _Operation],
        verbspecs: list[VerbSpec],
        rate_limit: RateLimitConfig,
        spec_title: str = "",
    ) -> None:
        super().__init__(base_url=base_url, rate_limit=rate_limit, retry=RetryPolicy())
        self.id = adapter_id
        self._operations = operations
        self._verbspecs = verbspecs
        self._gate = ReviewGate()
        self._spec_title = spec_title

    # --- review gate ---------------------------------------------------------
    @property
    def activated(self) -> bool:
        return self._gate.activated

    @property
    def review_gate(self) -> ReviewGate:
        return self._gate

    def review_and_activate(self, reviewer: str) -> ReviewGate:
        """Record human review and activate the adapter (SEC-22). Only after this
        may the registry create bindings for the adapter's verbs."""
        self._gate.activate(reviewer)
        return self._gate

    # --- contract surface ----------------------------------------------------
    def describe(self) -> list[VerbSpec]:
        return list(self._verbspecs)

    def _handlers(self) -> dict[str, Handler]:
        # One typed handler closure per derived operation.
        return {verb: functools.partial(self._invoke, verb) for verb in self._operations}

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if not self._gate.activated:
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    "generated adapter is inert pending human review (SEC-22)",
                )
            )
        return await super().execute(verb, params, credential, context)

    async def _invoke(
        self, verb: str, params: dict[str, Any], client: Any, context: InvocationContext
    ) -> Result:
        op = self._operations[verb]
        path = op.path
        for name in op.path_params:
            if name not in params:
                return Result.failure(
                    AdapterError(ErrorClass.INVALID, f"missing path parameter {name}")
                )
            path = path.replace("{%s}" % name, str(params[name]))
        query = {name: params[name] for name in op.query_params if name in params}
        headers = {name: str(params[name]) for name in op.header_params if name in params}
        json_body = params.get("body") if op.has_body else None

        if op.method == "get" and op.pagination == "link":
            items = [
                item
                async for item in self.paginate(
                    client,
                    path,
                    params=query or None,
                    items_key=op.items_key,
                    next_key=op.next_key,
                )
            ]
            return Result.success({"items": items, "count": len(items)})
        if op.method == "get" and op.pagination == "offset":
            items = [
                item
                async for item in self.paginate_offset(
                    client, path, params=query or None, items_key=op.items_key
                )
            ]
            return Result.success({"items": items, "count": len(items)})

        body = await self.request(
            client,
            op.method.upper(),
            path,
            params=query or None,
            json=json_body,
            headers=headers or None,
        )
        return Result.success(body)

    # --- reviewable artefact (SEC-22) ---------------------------------------
    def render_source(self) -> str:
        """Emit a human-reviewable Python module for this generated adapter.

        The runtime instance already carries every behaviour; this string is the
        artefact a reviewer reads before calling :meth:`review_and_activate`.
        """
        lines: list[str] = [
            '"""Generated adapter (US-ADP-01). Source spec: '
            f'{self._spec_title or "unknown"}.',
            "",
            "Derived deterministically from an OpenAPI document. Inherits retry/",
            "backoff, error mapping, rate-limit cooperation and pagination from",
            "HttpAdapter. INERT until a human reviewer activates it (SEC-22).",
            '"""',
            "from __future__ import annotations",
            "",
            "from nankle.adapters.http_base import HttpAdapter, RateLimitConfig",
            "",
            "",
            f"class {self._class_name()}(HttpAdapter):",
            f"    id = {self.id!r}",
            f"    version = {self.version!r}",
            f"    base_url = {self.base_url!r}",
            "    rate_limit_config = RateLimitConfig("
            f"max={self.rate_limit.max}, per={self.rate_limit.per!r})",
            "",
            "    # verb -> (method, path, consequence, pagination)",
            "    OPERATIONS = {",
        ]
        for verb, op in self._operations.items():
            lines.append(
                f"        {verb!r}: ({op.method.upper()!r}, {op.path!r}, "
                f"{op.consequence!r}, {op.pagination!r}),"
            )
        lines.append("    }")
        lines.append("")
        lines.append("    # Typed handlers are built from OPERATIONS at load time")
        lines.append("    # (see nankle.adapters.generator.GeneratedAdapter).")
        lines.append("")
        return "\n".join(lines)

    def _class_name(self) -> str:
        parts = [p for p in self.id.replace("-", "_").split("_") if p]
        return "".join(p.capitalize() for p in parts) + "Adapter" or "GeneratedAdapter"


# --- the generator entrypoint -------------------------------------------------
def generate_adapter_from_spec(
    spec: dict[str, Any] | str, *, adapter_id: str
) -> GeneratedAdapter:
    """Build a working (but inert) :class:`GeneratedAdapter` from an OpenAPI doc.

    ``spec`` may be a parsed dict, an http(s) URL, a file path, or raw JSON/YAML
    text. No LLM is involved; the transform is deterministic and offline-safe
    (US-ADP-01, SEC-22). The returned adapter is inert until reviewed.
    """
    doc = _load_spec(spec)
    if not isinstance(doc, dict):
        raise ValueError("openapi spec did not parse to a mapping")

    base_url = _base_url(doc)
    default_rl = _default_rate_limit(doc)
    operations: dict[str, _Operation] = {}
    verbspecs: list[VerbSpec] = []

    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        common_params = item.get("parameters") or []
        for method, operation in item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            op, vspec = _build_operation(
                doc, path, method.lower(), operation, common_params, default_rl
            )
            if op.verb_id in operations:
                continue  # first operation wins on a duplicate operationId
            operations[op.verb_id] = op
            verbspecs.append(vspec)

    title = (doc.get("info") or {}).get("title", "")
    return GeneratedAdapter(
        adapter_id=adapter_id,
        base_url=base_url,
        operations=operations,
        verbspecs=verbspecs,
        rate_limit=default_rl,
        spec_title=str(title),
    )


# --- spec loading -------------------------------------------------------------
def _load_spec(spec: dict[str, Any] | str) -> Any:
    if isinstance(spec, dict):
        return spec
    if not isinstance(spec, str):
        raise TypeError("spec must be a dict or a str (url / path / raw document)")
    if spec.startswith("http://") or spec.startswith("https://"):
        text = _fetch(spec)
    elif "\n" not in spec and len(spec) < 4096 and os.path.exists(spec):
        with open(spec, "r", encoding="utf-8") as handle:
            text = handle.read()
    else:
        text = spec
    import yaml  # lazy; pyyaml parses JSON and YAML alike

    return yaml.safe_load(text)


def _fetch(url: str) -> str:
    import httpx  # lazy

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as exc:
        raise ValueError(
            f"could not fetch openapi spec from url ({type(exc).__name__})"
        ) from exc


# --- derivation ---------------------------------------------------------------
def _build_operation(
    doc: dict[str, Any],
    path: str,
    method: str,
    operation: dict[str, Any],
    common_params: list[Any],
    default_rl: RateLimitConfig,
) -> tuple[_Operation, VerbSpec]:
    verb_id = operation.get("operationId") or _synth_verb_id(method, path)
    noun_id = _noun_of(operation, verb_id, path)

    params = [_deref(doc, p) for p in (list(common_params) + list(operation.get("parameters") or []))]
    path_params = tuple(p["name"] for p in params if p.get("in") == "path" and "name" in p)
    query_params = tuple(p["name"] for p in params if p.get("in") == "query" and "name" in p)
    header_params = tuple(p["name"] for p in params if p.get("in") == "header" and "name" in p)

    body_schema, body_required = _request_body(doc, operation)
    has_body = body_schema is not None
    input_schema = _input_schema(params, body_schema, body_required)

    output_schema, items_key, next_key, pagination = _output_and_pagination(
        doc, operation, query_params
    )
    consequence = "high" if method in _MUTATING else "low"
    rate_limit = _rate_from(operation) or default_rl

    op = _Operation(
        verb_id=verb_id,
        noun_id=noun_id,
        method=method,
        path=path,
        path_params=path_params,
        query_params=query_params,
        header_params=header_params,
        has_body=has_body,
        consequence=consequence,
        pagination=pagination,
        items_key=items_key,
        next_key=next_key,
    )
    vspec = VerbSpec(
        verb_id=verb_id,
        noun_id=noun_id,
        input_schema=input_schema,
        output_schema=output_schema,
        consequence=consequence,
        description=operation.get("summary") or operation.get("description") or "",
        rate_limit=rate_limit.as_spec(),
    )
    return op, vspec


def _synth_verb_id(method: str, path: str) -> str:
    segments = [seg for seg in path.strip("/").split("/") if seg and not seg.startswith("{")]
    return "_".join([method, *segments]) or method


def _noun_of(operation: dict[str, Any], verb_id: str, path: str) -> str:
    tags = operation.get("tags")
    if isinstance(tags, list) and tags:
        return str(tags[0])
    if "." in verb_id:
        return verb_id.split(".", 1)[0]
    for seg in path.strip("/").split("/"):
        if seg and not seg.startswith("{"):
            return seg
    return verb_id


def _request_body(
    doc: dict[str, Any], operation: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None, False
    request_body = _deref(doc, request_body)
    required = bool(request_body.get("required"))
    content = request_body.get("content") or {}
    for ctype, media in content.items():
        if "json" in ctype and isinstance(media, dict):
            return (media.get("schema") or {"type": "object"}), required
    return ({"type": "object"} if content else None), required


def _input_schema(
    params: list[dict[str, Any]],
    body_schema: dict[str, Any] | None,
    body_required: bool,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in params:
        name = param.get("name")
        if not name:
            continue
        properties[name] = param.get("schema") or {"type": "string"}
        if param.get("required"):
            required.append(name)
    if body_schema is not None:
        properties["body"] = body_schema
        if body_required:
            required.append("body")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def _output_and_pagination(
    doc: dict[str, Any], operation: dict[str, Any], query_params: tuple[str, ...]
) -> tuple[dict[str, Any], str, str, str | None]:
    responses = operation.get("responses") or {}
    schema: dict[str, Any] = {}
    for code in ("200", "201", "202", "2XX", "default"):
        if code not in responses:
            continue
        response = _deref(doc, responses[code])
        content = response.get("content") or {}
        for ctype, media in content.items():
            if "json" in ctype and isinstance(media, dict):
                schema = media.get("schema") or {}
                break
        if schema:
            break

    props = schema.get("properties") if isinstance(schema, dict) else None
    props = props or {}
    items_key = "items"
    next_key = "next"
    pagination: str | None = None
    for cand in _ITEMS_KEYS:
        if cand in props:
            items_key = cand
            break
    for cand in _NEXT_KEYS:
        if cand in props:
            next_key = cand
            pagination = "link"
            break
    if pagination is None:
        lowered = {q.lower() for q in query_params}
        if lowered & set(_OFFSET_PARAMS):
            pagination = "offset"
    return (schema or {"type": "object"}), items_key, next_key, pagination


def _rate_from(node: dict[str, Any]) -> RateLimitConfig | None:
    raw = node.get("x-ratelimit") or node.get("x-rate-limit") or node.get("x-rateLimit")
    if isinstance(raw, dict):
        return RateLimitConfig(
            max=int(raw.get("max", raw.get("limit", 600))),
            per=str(raw.get("per", "minute")),
            scope=str(raw.get("scope", "tenant")),
        )
    return None


def _default_rate_limit(doc: dict[str, Any]) -> RateLimitConfig:
    return _rate_from(doc) or RateLimitConfig(max=600, per="minute", scope="tenant")


def _base_url(doc: dict[str, Any]) -> str:
    servers = doc.get("servers")
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = servers[0].get("url", "")
        if isinstance(url, str) and url.startswith("http"):
            return url.rstrip("/")
    # OpenAPI / Swagger 2.0 fallback
    host = doc.get("host")
    if host:
        scheme = (doc.get("schemes") or ["https"])[0]
        return f"{scheme}://{host}{doc.get('basePath', '')}".rstrip("/")
    return ""


# --- local $ref resolution ----------------------------------------------------
def _deref(doc: dict[str, Any], node: Any, seen: tuple[str, ...] = ()) -> Any:
    """Inline local ``$ref`` pointers so derived schemas are self-contained.

    Cycles are broken by returning ``{}`` for an already-seen ref.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in seen:
                return {}
            target = _pointer(doc, ref)
            if target is None:
                return {}
            resolved = _deref(doc, target, seen + (ref,))
            extra = {k: v for k, v in node.items() if k != "$ref"}
            if extra and isinstance(resolved, dict):
                resolved = {**resolved, **_deref(doc, extra, seen)}
            return resolved
        return {k: _deref(doc, v, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref(doc, v, seen) for v in node]
    return node


def _pointer(doc: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    cursor: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor
