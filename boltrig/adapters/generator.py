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

import os
from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.adapters.http_base import RateLimitConfig

# Runtime classes moved to generated_adapter.py (arc-1); re-exported because
# callers import them from here (control_generated_adapter, lifecycle tests).
from .generated_adapter import (  # noqa: F401
    GeneratedAdapter as GeneratedAdapter,
    ReviewGate as ReviewGate,
    _Operation as _Operation,
)

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_MUTATING = ("post", "put", "patch", "delete")
_ITEMS_KEYS = ("value", "items", "results", "data", "records")
_NEXT_KEYS = ("@odata.nextLink", "nextLink", "next", "next_cursor", "nextPageToken")
_OFFSET_PARAMS = ("startat", "offset", "page", "cursor")
# A fetched openapi spec larger than this is hostile or broken, not a spec.
_MAX_SPEC_BYTES = 4 * 1024 * 1024


# --- the generator entrypoint -------------------------------------------------
def generate_adapter_from_spec(
    spec: dict[str, Any] | str,
    *,
    adapter_id: str,
    allow_local_paths: bool = False,
    network_config: dict[str, Any] | None = None,
) -> GeneratedAdapter:
    """Build a working (but inert) :class:`GeneratedAdapter` from an OpenAPI doc.

    ``spec`` may be a parsed dict, an http(s) URL, a file path, or raw JSON/YAML
    text. No LLM is involved; the transform is deterministic and offline-safe
    (US-ADP-01, SEC-22). The returned adapter is inert until reviewed. A URL is
    fetched through the egress guard (pinned, no redirects - INJ-02/SEC-61); a
    local file path requires the explicit ``allow_local_paths`` opt-in.
    ``network_config`` (the manifest NetworkConfig, SEC-52) binds BOTH the spec
    fetch and the generated adapter's own egress calls.
    """
    doc = _load_spec(
        spec, allow_local_paths=allow_local_paths, network_config=network_config
    )
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
        network_config=network_config,
    )


# --- spec loading -------------------------------------------------------------
def _load_spec(
    spec: dict[str, Any] | str,
    *,
    allow_local_paths: bool = False,
    network_config: dict[str, Any] | None = None,
) -> Any:
    if isinstance(spec, dict):
        return spec
    if not isinstance(spec, str):
        raise TypeError("spec must be a dict or a str (url / path / raw document)")
    if spec.startswith("http://") or spec.startswith("https://"):
        text = _fetch(spec, network_config)
    elif "\n" not in spec and len(spec) < 4096 and os.path.exists(spec):
        if not allow_local_paths:
            # Reading an arbitrary local path is an explicit opt-in: a spec
            # string must not silently double as a file read.
            raise ValueError(
                "loading an openapi spec from a local file requires "
                "allow_local_paths=True"
            )
        with open(spec, "r", encoding="utf-8") as handle:
            text = handle.read()
    else:
        text = spec
    import yaml  # lazy; pyyaml parses JSON and YAML alike

    return yaml.safe_load(text)


def _fetch(url: str, network_config: dict[str, Any] | None = None) -> str:
    import httpx  # lazy

    from boltrig.adapters.egress import EgressBlocked, pinned_sync_client

    # SSRF (INJ-02, CLOUD-03, SEC-61): the fetch goes through the same egress
    # guard as every other adapter - the target is vetted and the connection
    # pinned to the audited IP, and redirects are never followed into internal
    # space. A metadata/internal URL is refused BEFORE any network call. The
    # manifest NetworkConfig rides the same call (SEC-52): an air-gap /
    # allow-list posture binds the spec fetch, not just web.fetch. Bounded read
    # (streamed): resp.text buffered a hostile multi-GB body into kernel memory
    # before YAML ever parsed it; a spec is kilobytes.
    try:
        if network_config:
            client = pinned_sync_client(url, network_config, timeout=15.0)
        else:  # plain signature: an injected seam sees exactly what it sees today
            client = pinned_sync_client(url, timeout=15.0)
        with client as http_client:
            with http_client.stream("GET", url) as resp:
                resp.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes(65536):
                    size += len(chunk)
                    if size > _MAX_SPEC_BYTES:
                        raise ValueError(
                            f"openapi spec url exceeded the {_MAX_SPEC_BYTES}-byte cap"
                        )
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
    except EgressBlocked as exc:
        raise ValueError(f"openapi spec url refused by the egress guard: {exc}") from exc
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
