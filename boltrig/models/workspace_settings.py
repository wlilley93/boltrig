"""Per-workspace user settings, expressed as a key namespace rather than a column.

One account can run two businesses, and the ask included a different main
character companion in each. ``user_settings`` is PK ``(tenant_id, user_id,
key)`` and is read from a dozen places, so adding ``workspace_id`` to the key
would touch every one of them. The scope goes in the KEY instead:

    agent.character              the user's choice, every workspace
    ws:<workspace_id>:agent.character   their choice inside that workspace

Resolution is workspace override, then user override, then tenant default, and
:func:`resolve_user_settings` is the only place that ladder is written down. A
user with no per-workspace choice keeps the one they already had, which is why
the bare key remains a real fallback rather than a migration target.

ONLY the keys in :data:`WORKSPACE_SCOPED_SETTING_KEYS` are scoped. Approval
posture and the sensing consents are facts about a person and their hardware,
not about which business they are looking at, and silently forking them per
workspace would fork a consent decision.

``ws:`` is reserved by this module. Nothing else may write a key with that
prefix, or the two namespaces collide and a raw write becomes a way to set
another workspace's value.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The reserved prefix. One writer: :func:`workspace_setting_key`.
WORKSPACE_SETTING_PREFIX = "ws:"

#: Settings that differ per workspace. Deliberately short: a key belongs here
#: only when the answer genuinely changes with which business the user is in.
WORKSPACE_SCOPED_SETTING_KEYS: frozenset[str] = frozenset(
    {
        "agent.character",
        "agent.character.skin",
    }
)


def workspace_setting_key(workspace_id: str, key: str) -> str:
    """The stored key for ``key`` inside ``workspace_id``."""
    return f"{WORKSPACE_SETTING_PREFIX}{workspace_id}:{key}"


def is_workspace_setting_key(key: str) -> bool:
    """True for a stored key that carries a workspace scope."""
    return key.startswith(WORKSPACE_SETTING_PREFIX)


def storage_key(key: str, workspace_id: str | None) -> str:
    """Where a write lands: namespaced for a scoped key inside a workspace,
    otherwise the bare key. Only a key in `WORKSPACE_SCOPED_SETTING_KEYS` is ever
    namespaced, and a caller at org scope always writes the bare key, which is
    what a user with one business has always had."""
    if workspace_id and key in WORKSPACE_SCOPED_SETTING_KEYS:
        return workspace_setting_key(workspace_id, key)
    return key


def resolve_user_settings(
    defaults: Mapping[str, Any],
    stored: Mapping[str, Any],
    workspace_id: str | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """The effective settings for this scope, and where each value came from.

    Namespaced keys never appear in the result under their raw name: they are
    storage, not API, and `is_workspace_setting_key` is what removes them. A
    caller at org scope therefore does not see another workspace's companion,
    and a caller inside one sees exactly the value that workspace will actually
    use.
    """
    bare = {key: value for key, value in stored.items() if not is_workspace_setting_key(key)}
    scoped: dict[str, Any] = {}
    if workspace_id:
        for key in WORKSPACE_SCOPED_SETTING_KEYS:
            namespaced = workspace_setting_key(workspace_id, key)
            if namespaced in stored:
                scoped[key] = stored[namespaced]
    values = {**dict(defaults), **bare, **scoped}
    sources = {
        key: (
            "workspace_override"
            if key in scoped
            else "user_override"
            if key in bare
            else "tenant_default"
        )
        for key in set(defaults) | set(bare) | set(scoped)
    }
    return values, sources


def workspace_setting_value(
    rows: Iterable[Any], key: str, workspace_id: str | None
) -> Any:
    """The effective value of one setting from raw ``UserSetting`` rows.

    The same ladder as :func:`resolve_user_settings`, for the callers that hold
    rows rather than a bag (the chat persona reads one key on every turn).
    """
    values = {getattr(row, "key", None): getattr(row, "value", None) for row in rows}
    if workspace_id and key in WORKSPACE_SCOPED_SETTING_KEYS:
        namespaced = workspace_setting_key(workspace_id, key)
        if namespaced in values:
            return values[namespaced]
    return values.get(key)
