"""Strict, deterministic policy for ephemeral-agent spawn routing.

Spawn rules are policy data, not executable predicates.  The only supported
predicate is an all-of match over caller-supplied intent tags.  A selected rule
may choose a capability, add reviewed skills and tighten depth, but it cannot
widen the caller's grants; the spawner still intersects every loaded skill's
tool requirements with the parent authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_RULE_KEYS = frozenset(
    {"name", "priority", "match", "capability", "skills", "max_depth"}
)
_MATCH_KEYS = frozenset({"intent_tags"})
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SKILL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_MAX_RULES = 128
_MAX_TAGS = 32
_MAX_SKILLS = 32
_MAX_PRIORITY = 1000
_MAX_DEPTH = 10


class SpawnRuleValidationError(ValueError):
    """A spawn-rule document is outside the closed policy schema."""


class SpawnRuleMatchError(ValueError):
    """A request cannot be resolved to one deterministic rule."""


@dataclass(frozen=True)
class SpawnRule:
    """One validated, immutable spawn-routing rule."""

    name: str
    priority: int
    intent_tags: tuple[str, ...]
    capability: str
    skills: tuple[str, ...] = ()
    max_depth: int | None = None

    @property
    def match(self) -> dict[str, list[str]]:
        """Compatibility projection using the manifest's public shape."""

        return {"intent_tags": list(self.intent_tags)}


@dataclass(frozen=True)
class SpawnRuleSelection:
    """The bounded rule identity/effects copied through a governed spawn."""

    rule_id: str
    priority: int
    matched_intent_tags: tuple[str, ...]
    capability: str
    skills_added: tuple[str, ...]
    max_depth: int | None

    def receipt(self) -> dict[str, Any]:
        return {
            "id": self.rule_id,
            "priority": self.priority,
            "matched_intent_tags": list(self.matched_intent_tags),
            "capability": self.capability,
            "skills_added": list(self.skills_added),
            "max_depth": self.max_depth,
        }


@dataclass(frozen=True)
class EffectiveSpawnRules:
    """One immutable serving snapshot and the source that selected it."""

    rules: tuple[SpawnRule, ...]
    source: str
    revision_id: int | None


@dataclass(frozen=True)
class SpawnRuleConflict:
    """An exact tag example that reaches more than one top-priority rule."""

    priority: int
    rules: tuple[str, ...]
    example_intent_tags: tuple[str, ...]

    def receipt(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "rules": list(self.rules),
            "example_intent_tags": list(self.example_intent_tags),
        }


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpawnRuleValidationError(f"{field} must be an object")
    return value


def _closed_keys(
    value: Mapping[str, Any], allowed: frozenset[str], *, field: str
) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise SpawnRuleValidationError(
            f"{field} has unsupported fields: {', '.join(unknown)}"
        )


def _identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise SpawnRuleValidationError(f"{field} must be a stable identifier")
    return value


def _bounded_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpawnRuleValidationError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise SpawnRuleValidationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _string_list(
    value: Any,
    *,
    field: str,
    pattern: re.Pattern[str],
    maximum: int,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise SpawnRuleValidationError(f"{field} must be an array")
    if not allow_empty and not value:
        raise SpawnRuleValidationError(f"{field} must not be empty")
    if len(value) > maximum:
        raise SpawnRuleValidationError(
            f"{field} may contain at most {maximum} entries"
        )
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise SpawnRuleValidationError(f"{field} contains an invalid identifier")
        if item in out:
            raise SpawnRuleValidationError(f"{field} contains duplicate '{item}'")
        out.append(item)
    return tuple(out)


def parse_intent_tags(value: Any) -> tuple[str, ...]:
    """Validate the request-side intent vocabulary used by the matcher."""

    return _string_list(
        value,
        field="prefer.intent_tags",
        pattern=_TAG_RE,
        maximum=_MAX_TAGS,
        allow_empty=True,
    )


def _parse_spawn_rule(raw_value: Any, *, index: int) -> SpawnRule:
    field = f"spawn_rules[{index}]"
    raw = _mapping(raw_value, field=field)
    _closed_keys(raw, _RULE_KEYS, field=field)
    missing = sorted(
        key
        for key in ("name", "priority", "match", "capability")
        if key not in raw
    )
    if missing:
        raise SpawnRuleValidationError(
            f"{field} is missing required fields: {', '.join(missing)}"
        )

    match = _mapping(raw["match"], field=f"{field}.match")
    _closed_keys(match, _MATCH_KEYS, field=f"{field}.match")
    if "intent_tags" not in match:
        raise SpawnRuleValidationError(
            f"{field}.match is missing required field: intent_tags"
        )
    max_depth_raw = raw.get("max_depth")
    return SpawnRule(
        name=_identifier(raw["name"], field=f"{field}.name"),
        priority=_bounded_int(
            raw["priority"],
            field=f"{field}.priority",
            minimum=0,
            maximum=_MAX_PRIORITY,
        ),
        intent_tags=_string_list(
            match["intent_tags"],
            field=f"{field}.match.intent_tags",
            pattern=_TAG_RE,
            maximum=_MAX_TAGS,
            allow_empty=False,
        ),
        capability=_identifier(
            raw["capability"], field=f"{field}.capability"
        ),
        skills=_string_list(
            raw.get("skills", []),
            field=f"{field}.skills",
            pattern=_SKILL_RE,
            maximum=_MAX_SKILLS,
            allow_empty=True,
        ),
        max_depth=(
            None
            if max_depth_raw is None
            else _bounded_int(
                max_depth_raw,
                field=f"{field}.max_depth",
                minimum=1,
                maximum=_MAX_DEPTH,
            )
        ),
    )


def parse_spawn_rules(value: Any) -> tuple[SpawnRule, ...]:
    """Parse the closed spawn-rule schema or reject the whole policy."""

    if not isinstance(value, (list, tuple)):
        raise SpawnRuleValidationError("spawn_rules must be an array")
    if len(value) > _MAX_RULES:
        raise SpawnRuleValidationError(
            f"spawn_rules may contain at most {_MAX_RULES} rules"
        )

    rules: list[SpawnRule] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        rule = _parse_spawn_rule(item, index=index)
        if rule.name in names:
            raise SpawnRuleValidationError(
                f"duplicate spawn rule name '{rule.name}'"
            )
        names.add(rule.name)
        rules.append(rule)
    return tuple(rules)


def select_spawn_rule(
    rules: Sequence[SpawnRule], intent_tags: Sequence[str]
) -> SpawnRule | None:
    """Choose the unique highest-priority all-of match.

    List order and predicate specificity never break a tie.  Two matching rules
    at the same highest priority are an invalid policy state and fail closed.
    """

    requested = frozenset(intent_tags)
    matches = [
        rule for rule in rules if frozenset(rule.intent_tags).issubset(requested)
    ]
    if not matches:
        return None
    priority = max(rule.priority for rule in matches)
    winners = [rule for rule in matches if rule.priority == priority]
    if len(winners) != 1:
        names = ", ".join(sorted(rule.name for rule in winners))
        raise SpawnRuleMatchError(
            f"spawn rules tie at priority {priority}: {names}"
        )
    return winners[0]


def spawn_rule_conflicts(
    rules: Sequence[SpawnRule],
) -> tuple[SpawnRuleConflict, ...]:
    """Find every reachable top-priority tie with a deterministic example.

    If a tie is reachable, the union of any two tied rules' required tags also
    reaches that tie: a higher-priority rule matching the union would have
    matched the original request too. Pairwise unions are therefore a complete
    bounded analysis for the closed all-of predicate vocabulary.
    """

    found: dict[tuple[int, tuple[str, ...]], SpawnRuleConflict] = {}
    for index, left in enumerate(rules):
        for right in rules[index + 1 :]:
            if left.priority != right.priority:
                continue
            example = tuple(sorted(set(left.intent_tags) | set(right.intent_tags)))
            requested = frozenset(example)
            matches = [
                rule
                for rule in rules
                if frozenset(rule.intent_tags).issubset(requested)
            ]
            if not matches:
                continue
            priority = max(rule.priority for rule in matches)
            winners = tuple(
                sorted(rule.name for rule in matches if rule.priority == priority)
            )
            if len(winners) < 2:
                continue
            key = (priority, winners)
            prior = found.get(key)
            if prior is None or example < prior.example_intent_tags:
                found[key] = SpawnRuleConflict(
                    priority=priority,
                    rules=winners,
                    example_intent_tags=example,
                )
    return tuple(found[key] for key in sorted(found))


async def effective_spawn_rules(
    store: Any,
    tenant_id: str,
    base_rules: Sequence[SpawnRule],
) -> EffectiveSpawnRules:
    """Resolve the same latest persisted policy used by governed spawns."""
    from .spawn_rule_revisions import effective_spawn_rules as resolve

    return await resolve(
        store,
        tenant_id,
        base_rules,
    )


def apply_spawn_rule(
    rules: Sequence[SpawnRule],
    *,
    skills: Sequence[str],
    prefer: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any], SpawnRuleSelection | None]:
    """Resolve one policy snapshot into effective skills/routing.

    ``capability``, ``runtime`` and ``cost_tier`` are alternative routing pins.
    Once a rule matches, a caller-supplied pin must not compete with it: an
    identical capability pin is accepted, while any conflicting selector is
    refused rather than silently ignored.
    """

    request_skills = list(dict.fromkeys(skills))
    effective_prefer = dict(prefer)
    if "intent_tags" not in effective_prefer:
        return request_skills, effective_prefer, None
    tags = parse_intent_tags(effective_prefer["intent_tags"])
    rule = select_spawn_rule(rules, tags)
    if rule is None:
        return request_skills, effective_prefer, None

    pinned = effective_prefer.get("capability")
    if pinned is not None and pinned != rule.capability:
        raise SpawnRuleMatchError(
            f"spawn rule '{rule.name}' conflicts with requested capability"
        )
    for selector in ("runtime", "cost_tier"):
        if effective_prefer.get(selector) is not None:
            raise SpawnRuleMatchError(
                f"spawn rule '{rule.name}' conflicts with requested {selector}"
            )

    effective_skills = list(request_skills)
    for skill in rule.skills:
        if skill not in effective_skills:
            effective_skills.append(skill)
    added = tuple(skill for skill in effective_skills if skill not in request_skills)
    effective_prefer["capability"] = rule.capability
    selection = SpawnRuleSelection(
        rule_id=rule.name,
        priority=rule.priority,
        matched_intent_tags=rule.intent_tags,
        capability=rule.capability,
        skills_added=added,
        max_depth=rule.max_depth,
    )
    return effective_skills, effective_prefer, selection

__all__ = [
    "EffectiveSpawnRules",
    "SpawnRule",
    "SpawnRuleConflict",
    "SpawnRuleMatchError",
    "SpawnRuleSelection",
    "SpawnRuleValidationError",
    "apply_spawn_rule",
    "effective_spawn_rules",
    "parse_intent_tags",
    "parse_spawn_rules",
    "select_spawn_rule",
    "spawn_rule_conflicts",
]
