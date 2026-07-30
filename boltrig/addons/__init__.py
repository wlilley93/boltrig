"""Addons: integration-specific behaviour that ships only where it is provisioned.

WHY THIS EXISTS. Boltrig ships two ways - alone, and alongside an Opbox that
provisions it - and the second had been leaking into the first. Opbox specifics
were welded into generic modules: the on-behalf adapter id defaulted to ``"opbox"``
in two separate files, and ``mcp_consumer`` carried a regex for Opbox's
``riskClass=`` description token, so a boltrig that has never heard of Opbox still
carried Opbox's consequence vocabulary and Opbox's adapter name.

An addon is the seam that fixes that WITHOUT forking. It is a named, versioned
bundle contributing three things, any of which may be absent:

  * ``harness`` - a prompt fragment appended below the base harness, so an
    integration can teach the model about ITS tools without editing the base text
    every boltrig ships;
  * ``adapter_id`` - the consumed-server noun whose bearer a run seals per-turn;
  * ``consequence_hint`` - how to read a consequence tier off THAT server's tool
    projection, when it declares no structured field.

THE PINNED VERSION IS COMPOSED, NOT FORKED. The birth profile keeps ONE name.
Its version is the base version plus semver BUILD METADATA naming the active
addons (``1.1.0+opbox-1.0.0``), which both the adapter and the admission derive
through :func:`composed_version`, so they cannot disagree - the same
cannot-drift property the kernel-tools lane already relies on. Adding an
integration therefore moves the pin forward; it never creates a second profile
lineage to maintain in parallel.

FAIL-CLOSED ON A TYPO. ``BOLTRIG_ADDONS=opbx`` raises rather than quietly
shipping a boltrig with no Opbox seam at all. A silent nothing is the failure
mode this estate keeps paying for: the turn completes, the agent apologises, and
nothing in the record says the integration was never loaded.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

ENV_VAR = "BOLTRIG_ADDONS"
REQUIREMENT_KINDS = ("adapter", "component", "environment", "credential_ref")

# Per-addon harness bound. See ``Addon.__post_init__``: this protects the
# governance floor's salience, not just the birth-policy byte cap.
MAX_ADDON_HARNESS_BYTES = 4096


class AddonError(RuntimeError):
    """An addon was requested that is not registered, or is not a valid addon."""


@dataclass(frozen=True)
class AddonRequirement:
    """One declarative, kernel-evaluated add-on readiness requirement.

    ``ref`` is private evaluation input. Public projections expose only ``id``
    and ``kind`` so deployment-variable names and credential references never
    leave the kernel.
    """

    id: str
    kind: str
    ref: str = field(repr=False)
    required: bool = True

    def __post_init__(self) -> None:
        if (
            not self.id
            or len(self.id) > 128
            or not self.id.replace("-", "").replace("_", "").replace(".", "").isalnum()
        ):
            raise AddonError(
                "addon requirement id must be bounded alphanumeric text "
                "(hyphens, underscores and dots allowed)"
            )
        if self.kind not in REQUIREMENT_KINDS:
            raise AddonError(
                "addon requirement kind must be one of: "
                + ", ".join(REQUIREMENT_KINDS)
            )
        if not isinstance(self.ref, str) or not self.ref.strip() or len(self.ref) > 256:
            raise AddonError("addon requirement ref must be non-empty bounded text")
        if "\x00" in self.ref:
            raise AddonError("addon requirement ref cannot contain NUL")
        if type(self.required) is not bool:
            raise AddonError("addon requirement required must be a boolean")


@dataclass(frozen=True)
class Addon:
    """One integration's contribution. Every field beyond identity is optional."""

    name: str
    version: str
    harness: str = ""
    adapter_id: str | None = None
    consequence_hint: Callable[[Mapping[str, object]], str | None] | None = field(
        default=None, compare=False
    )
    requirements: tuple[AddonRequirement, ...] = ()

    def __post_init__(self) -> None:
        # The name and version travel INTO a pinned semver's build metadata, so
        # they are bounded to what that grammar accepts. Anything else would
        # produce a profile version the policy layer refuses at compile time -
        # better to refuse here, where the addon is declared.
        if not self.name or not self.name.replace("-", "").isalnum():
            raise AddonError("addon name must be alphanumeric (hyphens allowed)")
        if not self.version or not self.version.replace(".", "").isdigit():
            raise AddonError("addon version must be a numeric dotted version")
        # The harness fragment is BOUNDED. It is appended to an attested birth
        # policy that the runtime caps outright (128KiB), and more importantly the
        # governance floor is only load-bearing while the model can still see it:
        # an addon that contributes pages of text pushes the cage out of
        # attention without ever tripping a limit. An integration needs a
        # paragraph about its own tools, not a manual.
        if len(self.harness.encode("utf-8")) > MAX_ADDON_HARNESS_BYTES:
            raise AddonError(
                f"addon {self.name!r} harness exceeds {MAX_ADDON_HARNESS_BYTES} bytes"
            )
        if not isinstance(self.requirements, tuple) or any(
            not isinstance(requirement, AddonRequirement)
            for requirement in self.requirements
        ):
            raise AddonError("addon requirements must be a tuple of AddonRequirement")
        requirement_ids = [requirement.id for requirement in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise AddonError(f"addon {self.name!r} requirement ids must be unique")


_REGISTRY: dict[str, Addon] = {}


def register(addon: Addon) -> Addon:
    """Register ``addon`` under its name. Re-registering the same name replaces it."""

    if not isinstance(addon, Addon):
        raise AddonError("register() takes an Addon")
    _REGISTRY[addon.name] = addon
    return addon


def registered() -> tuple[Addon, ...]:
    return tuple(sorted(_REGISTRY.values(), key=lambda a: a.name))


def _requested(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(sorted({part.strip() for part in raw.split(",") if part.strip()}))


def active_addons(raw: str | None = None) -> tuple[Addon, ...]:
    """The addons this deployment runs, in name order.

    Enabled by ``BOLTRIG_ADDONS`` (comma-separated). A boltrig shipping alone sets
    nothing and gets ``()`` - no Opbox vocabulary, no Opbox adapter name, no Opbox
    harness text. A name that is not registered raises: see the module docstring.
    """

    if raw is None:
        raw = os.environ.get(ENV_VAR)
    names = _requested(raw)
    missing = [name for name in names if name not in _REGISTRY]
    if missing:
        raise AddonError(
            f"{ENV_VAR} names unregistered addon(s): {', '.join(missing)}; "
            f"registered: {', '.join(sorted(_REGISTRY)) or '(none)'}"
        )
    return tuple(_REGISTRY[name] for name in names)


def composed_version(base_version: str, addons: tuple[Addon, ...]) -> str:
    """``base_version`` alone, or with build metadata naming the active addons.

    ``1.1.0`` with no addons; ``1.1.0+opbox-1.0.0`` with one. Build metadata is
    dot-separated per semver, and each addon contributes one ``name-version``
    identifier, so the pin states exactly which integrations composed it.
    """

    if not addons:
        return base_version
    parts = ".".join(f"{addon.name}-{addon.version}" for addon in addons)
    return f"{base_version}+{parts}"


def adapter_id_for(addons: tuple[Addon, ...]) -> str | None:
    """The on-behalf adapter id contributed by the active addons, if exactly one is.

    Two addons both claiming to be the on-behalf server is an ambiguity a run
    cannot resolve at seal time, so it refuses rather than picking one.
    """

    claimed = [addon for addon in addons if addon.adapter_id]
    if not claimed:
        return None
    if len(claimed) > 1:
        raise AddonError(
            "more than one active addon claims the on-behalf adapter: "
            + ", ".join(f"{a.name}={a.adapter_id}" for a in claimed)
        )
    return claimed[0].adapter_id


def consequence_hint_for(
    addons: tuple[Addon, ...] | None, tool: Mapping[str, object]
) -> str | None:
    """The HIGHEST consequence any addon reads off ``tool``. Defaults to REGISTERED.

    TWO RULES, both learned the hard way.

    HIGHEST, not first. First-wins let one addon's ``low`` mask another's ``high``
    and drop a tool below the approval gate - the same defect this seam already
    fixed between an addon and a server's MCP annotations, left in place here
    between two addons.

    REGISTERED, not active. Reading a server's risk vocabulary is not an authority
    grant: with the rule above it can only ever RAISE a consequence. Gating it on
    ``BOLTRIG_ADDONS`` therefore bought nothing and cost the approval gate -
    measured: an opbox tool carrying ``riskClass=DESTRUCTIVE`` registered as
    ``low`` on any deployment that had not set the flag, so the HITL gate never
    fired on it. Activation stays meaningful where it belongs: the HARNESS text,
    which is compiled into an attested, hashed birth profile.
    """

    highest: str | None = None
    for addon in registered() if addons is None else addons:
        if addon.consequence_hint is None:
            continue
        hint = addon.consequence_hint(tool)
        if hint == "high":
            return "high"
        if hint is not None and highest is None:
            highest = hint
    return highest


def on_behalf_adapter_id(addons: tuple[Addon, ...] | None = None) -> str | None:
    """The adapter a run seals its on-behalf bearer for.

    ``BOLTRIG_OBO_ADAPTER_ID`` wins when set (a differently-named deployment of
    the same integration); otherwise the active addon that claims one. ``None``
    when nothing claims it, and callers must treat that as "do not seal" rather
    than substituting a name - a hardcoded default here is what put ``"opbox"``
    into two generic modules in the first place.
    """

    override = os.environ.get("BOLTRIG_OBO_ADAPTER_ID")
    if override:
        return override
    if addons is not None:
        return adapter_id_for(addons)
    claimed = adapter_id_for(active_addons())
    if claimed:
        return claimed
    # Fall back to what this BUILD ships, not just what the deployment activated.
    # Failing to seal is not fail-safe: dispatch then uses the adapter's STATIC
    # SERVICE credential, which carries the adapter's own authority rather than the
    # caller's clamped bearer - so a missing flag WIDENS what the downstream call
    # may do, silently, on a turn that still succeeds. Identity is not authority:
    # sealing for the adapter that owns the bearer is strictly the narrower choice.
    # Only when exactly one registered addon claims it, so a multi-integration
    # build stays unambiguous rather than guessing.
    single = [addon for addon in registered() if addon.adapter_id]
    return single[0].adapter_id if len(single) == 1 else None


ENTRY_POINT_GROUP = "boltrig.addons"


def load_entry_point_addons() -> tuple[str, ...]:
    """Register addons published by OTHER installed packages. Returns their names.

    This is the out-of-tree seam: a companion product depends on boltrig, declares

        [project.entry-points."boltrig.addons"]
        billandben = "billandben.boltrig_addon:ADDON"

    and its Addon becomes registrable without a boltrig code change. The entry
    point may resolve to an ``Addon`` or to a zero-argument callable returning one.

    A broken entry point RAISES rather than being skipped: a companion product
    that fails to load is the silent-nothing failure this module exists to avoid.
    """

    from importlib.metadata import entry_points

    loaded: list[str] = []
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            value = entry.load()
        except Exception as exc:  # noqa: BLE001 - re-raised with the name attached
            raise AddonError(
                f"addon entry point {entry.name!r} failed to load: "
                f"{type(exc).__module__}.{type(exc).__qualname__}"
            ) from exc
        addon = value() if callable(value) and not isinstance(value, Addon) else value
        if not isinstance(addon, Addon):
            raise AddonError(
                f"addon entry point {entry.name!r} resolved to "
                f"{type(addon).__qualname__}, not an Addon"
            )
        if addon.name in _REGISTRY:
            # An installed package must not be able to TAKE a name this build
            # already ships. ``register`` replaces by design (a build may override
            # its own), but reached from an entry point that becomes a hijack: the
            # squatter inherits the displaced addon's adapter claim, so the bearer a
            # chat turn seals is redirected to a server of the squatter's choosing,
            # and its consequence reading of the real server disappears with it.
            raise AddonError(
                f"addon entry point {entry.name!r} would replace the already "
                f"registered addon {addon.name!r}; names must be unique"
            )
        register(addon)
        loaded.append(addon.name)
    return tuple(loaded)


def load_builtin_addons() -> None:
    """Register the addons that ship in this distribution, then any installed ones.

    Registration is not activation: an addon does nothing until ``BOLTRIG_ADDONS``
    names it. Importing the module is what makes the name resolvable, so a
    deployment that enables ``opbox`` gets a clear error rather than a silent miss.
    """

    from . import opbox  # noqa: F401  (imported for its registration side effect)

    load_entry_point_addons()


load_builtin_addons()


__all__ = [
    "ENV_VAR",
    "REQUIREMENT_KINDS",
    "Addon",
    "AddonError",
    "AddonRequirement",
    "active_addons",
    "adapter_id_for",
    "composed_version",
    "consequence_hint_for",
    "load_builtin_addons",
    "register",
    "registered",
]
