"""Scoped memory helpers for Ultracode workflows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from boltrig.fleet.prompt_stack import wrap_untrusted
from boltrig.kernel.pii import contains_secret
from boltrig.models import GrantSet, InvocationContext

_MAX_ITEMS = 8
_MAX_CHARS = 2400


@dataclass(frozen=True)
class MemoryContext:
    """Compact memory text plus the exact scopes that were queried."""

    text: str
    count: int
    scopes: tuple[str, ...]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _repo_key(repo_root: str | None) -> str | None:
    return f"repo:{_digest(repo_root)}" if repo_root else None


def _branch_key(repo_root: str | None, branch: str | None) -> str | None:
    if not branch:
        return None
    basis = f"{repo_root or ''}@{branch}"
    return f"branch:{_digest(basis)}"


def _path_key(repo_root: str | None, path: str | None) -> str | None:
    if not path:
        return None
    norm = str(PurePosixPath(path))
    basis = f"{repo_root or ''}:{norm}"
    return f"path:{_digest(basis)}"


def _run_type_key(run_type: str | None) -> str | None:
    if not run_type:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in run_type)
    return f"run-type:{safe[:64]}"


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def memory_config(defaults: dict[str, Any], agent: dict[str, Any]) -> dict[str, Any]:
    """Merge workflow and agent memory knobs, agent values winning."""
    cfg = dict(defaults.get("memory") or {})
    cfg.update(dict(agent.get("memory") or {}))
    return cfg


def owner_scopes(context: InvocationContext) -> tuple[str, ...]:
    """Memory RBAC owner scopes derivable at this layer: the principal + org.

    Caller-supplied ``extra`` NEVER widens memory visibility: a ``memory_scopes``
    list arrives via ``/v1/spawn``'s caller-controlled ``body.context``, so
    honouring it would let a caller name any user:/department: scope and read
    another principal's memory. This mirrors the server-side derivation
    (``identity.rbac.memory_owner_scopes``: own user + org), minus department
    scopes, which this layer cannot derive from a verified role/scope - the only
    ``role``/``scope`` data available here rides in the same caller-controlled
    extra. Losing department-scoped recall in Ultracode is the deliberate cost of
    failing closed.
    """

    scopes: list[str] = []
    if context.on_behalf_of:
        scopes.append(f"user:{context.on_behalf_of}")
    scopes.append("org")
    return tuple(scopes)


def memory_keys(
    context: InvocationContext,
    defaults: dict[str, Any],
    agent: dict[str, Any],
) -> tuple[str, ...]:
    """Derive provenance keys for workspace/repo/branch/path/run type."""
    extra = dict(context.extra or {})
    repo_root = agent.get("repo_root") or defaults.get("repo_root") or extra.get("repo_root")
    branch = (
        agent.get("branch")
        or agent.get("git_branch")
        or defaults.get("branch")
        or extra.get("branch")
        or extra.get("git_branch")
    )
    run_type = agent.get("run_type") or defaults.get("run_type") or extra.get("run_type") or "ultracode"
    paths = (
        _paths(agent.get("file_path"))
        + _paths(agent.get("file_paths"))
        + _paths(defaults.get("file_path"))
        + _paths(defaults.get("file_paths"))
        + _paths(extra.get("file_path"))
        + _paths(extra.get("file_paths"))
    )

    keys: list[str | None] = [
        f"workspace:{context.workspace_id}" if context.workspace_id else None,
        _repo_key(str(repo_root) if repo_root else None),
        _branch_key(str(repo_root) if repo_root else None, str(branch) if branch else None),
        _run_type_key(str(run_type) if run_type else None),
    ]
    keys.extend(_path_key(str(repo_root) if repo_root else None, path) for path in paths)

    out: list[str] = []
    for key in keys:
        if key and key not in out:
            out.append(key)
    return tuple(out)


def memory_source_ref(context: InvocationContext, defaults: dict[str, Any], agent: dict[str, Any]) -> str:
    """Structured provenance string for Ultracode memory writes."""
    keys = memory_keys(context, defaults, agent)
    return "|".join(("ultracode", *keys))


def _allows_sensitive(context: InvocationContext) -> bool:
    return (context.extra or {}).get("data_class") == "sensitive"


def _has_recall_grant(context: InvocationContext) -> bool:
    grants = context.grants if isinstance(context.grants, GrantSet) else GrantSet.of()
    return grants.permits("memory.recall")


def _value(hit: Any, key: str, default: Any = "") -> Any:
    if isinstance(hit, dict):
        return hit.get(key, default)
    return getattr(hit, key, default)


def _source_ref(hit: Any) -> str:
    if isinstance(hit, dict):
        provenance = hit.get("provenance") if isinstance(hit.get("provenance"), dict) else {}
        return str(provenance.get("source_ref") or hit.get("source_ref") or "")
    return str(getattr(hit, "source_ref", "") or "")


def _bounded_lines(lines: list[str], max_chars: int) -> str:
    out: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > max_chars:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _hit_line(hit: Any) -> str | None:
    content = str(_value(hit, "content", "") or "").strip()
    if not content or contains_secret(content):
        return None
    source = _source_ref(hit) or str(_value(hit, "source_kind", ""))
    owner = str(_value(hit, "owner_scope", ""))
    kind = str(_value(hit, "kind", "memory"))
    return f"- [{kind} {owner} {source}] {content[:500]}"


def _matches_keys(hit: Any, keys: tuple[str, ...]) -> bool:
    ref = _source_ref(hit)
    if not ref or not ref.startswith("ultracode|"):
        return True
    current = set(keys)
    tokens = set(ref.split("|")[1:])
    for prefix in ("workspace:", "repo:", "branch:", "path:", "run-type:"):
        scoped = {token for token in tokens if token.startswith(prefix)}
        if scoped and not scoped.intersection(current):
            return False
    return True


def _query(defaults: dict[str, Any], agent: dict[str, Any], cfg: dict[str, Any]) -> str:
    return str(
        cfg.get("query")
        or agent.get("prompt")
        or agent.get("objective")
        or defaults.get("goal")
        or "ultracode"
    )


async def _adapter_recall(
    kernel: Any,
    tenant: str,
    context: InvocationContext,
    defaults: dict[str, Any],
    agent: dict[str, Any],
    cfg: dict[str, Any],
    scopes: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]] | None:
    if not hasattr(kernel, "invoke"):
        return None
    recall_ctx = replace(
        context,
        extra={**dict(context.extra or {}), "memory_scopes": list(scopes)},
    )
    try:
        out = await kernel.invoke(
            "memory",
            "memory.recall",
            {
                "query": _query(defaults, agent, cfg),
                "mode": str(cfg.get("mode") or "similarity"),
                "limit": limit,
            },
            recall_ctx,
        )
    except Exception:
        return None
    facts = out.get("facts") if isinstance(out, dict) else None
    return [fact for fact in facts if isinstance(fact, dict)] if isinstance(facts, list) else None


async def recall_memory(
    kernel: Any,
    tenant: str,
    context: InvocationContext,
    defaults: dict[str, Any],
    agent: dict[str, Any],
) -> MemoryContext:
    """Read compact scoped memory from store metadata, not global recall."""
    cfg = memory_config(defaults, agent)
    if cfg.get("enabled") is False:
        return MemoryContext("", 0, ())
    scopes = owner_scopes(context)
    if not _has_recall_grant(context):
        return MemoryContext("", 0, scopes)
    limit = max(1, min(int(cfg.get("limit") or _MAX_ITEMS), _MAX_ITEMS))
    max_chars = max(256, min(int(cfg.get("max_chars") or _MAX_CHARS), _MAX_CHARS))
    keys = memory_keys(context, defaults, agent)
    kinds = cfg.get("kinds")
    allowed_kinds = {str(k) for k in kinds} if isinstance(kinds, list) else None

    hits = await _adapter_recall(kernel, tenant, context, defaults, agent, cfg, scopes, limit)
    used_adapter = hits is not None
    if hits is None and hasattr(kernel.store, "list_memory_facts"):
        hits = []
        facts = await kernel.store.list_memory_facts(tenant, list(scopes), limit=limit * 2)
        hits.extend(
            f for f in facts if not getattr(f, "redacted", False) and _matches_keys(f, keys)
        )
    if hits is None:
        hits = []
    if not used_adapter and not hits and hasattr(kernel.store, "query_memory"):
        items = await kernel.store.query_memory(tenant, list(scopes), limit=limit * 2)
        hits.extend(item for item in items if _matches_keys(item, keys))
    if not _allows_sensitive(context):
        hits = [h for h in hits if _value(h, "data_class", "standard") != "sensitive"]
    if allowed_kinds is not None:
        hits = [h for h in hits if _value(h, "kind", "") in allowed_kinds]
    hits.sort(key=lambda h: _value(h, "created_at", None), reverse=True)

    lines = [line for hit in hits for line in [_hit_line(hit)] if line][:limit]
    text = _bounded_lines(lines, max_chars)
    return MemoryContext(text, len(lines), scopes)


def memory_prompt(memory: MemoryContext) -> str:
    """Prompt-safe memory block: recall is untrusted data, never instruction."""
    if not memory.text:
        return ""
    return wrap_untrusted("memory.recall", "ultracode", memory.text)


async def remember_run_summary(
    kernel: Any,
    tenant: str,
    context: InvocationContext,
    run_record: dict[str, Any],
    defaults: dict[str, Any],
) -> None:
    """Best-effort governed summary write through memory.remember."""
    cfg = dict(defaults.get("memory") or {})
    if cfg.get("enabled") is False or cfg.get("write_summaries") is False:
        return
    grants = context.grants if isinstance(context.grants, GrantSet) else GrantSet.of()
    if not grants.permits("memory.remember"):
        return
    scopes = owner_scopes(context)
    owner_scope = f"user:{context.on_behalf_of}" if context.on_behalf_of else None
    if owner_scope is None:
        owner_scope = next((s for s in scopes if s.startswith("department:")), None)
    if owner_scope is None:
        return
    status = run_record.get("status", "unknown")
    kind = "summary" if status in {"completed", "degraded"} else "lesson"
    phases = ", ".join(f"{p['id']}={p['status']}" for p in run_record.get("phases", []))
    content = (
        f"Ultracode {run_record.get('workflow_name', 'workflow')} finished {status}. "
        f"Phases: {phases or 'none'}."
    )[:800]
    if contains_secret(content):
        return
    summary_ctx = replace(
        context,
        run_id=run_record.get("run_id") or context.run_id,
        extra={**dict(context.extra or {}), "memory_scopes": list(scopes)},
    )
    try:
        await kernel.invoke(
            "memory",
            "memory.remember",
            {
                "content": content,
                "owner_scope": owner_scope,
                "kind": kind,
                "source_kind": "ultracode_run",
                "source_ref": (
                    f"{memory_source_ref(context, defaults, {})}|"
                    f"run:{run_record.get('run_id') or context.run_id or ''}"
                ),
                "data_class": (context.extra or {}).get("data_class", "standard"),
            },
            summary_ctx,
        )
    except Exception:
        return
