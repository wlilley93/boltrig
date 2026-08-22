"""Curated mapping packs: level 2 of capability matching (SPEC §5).

Level 1 is a plugin declaring ``implements:`` about itself. Level 2 is a
CURATOR declaring it on the plugin's behalf, as versioned data:

    opbox.create_matter  ->  matter.open@1

The distinction matters more than it looks. A level-1 claim is the provider
speaking about its own operation and, from a first-party adapter, is already a
governed act. A level-2 claim is a third party's opinion about somebody else's
API, so a pack binding always lands ``proposed`` and is not eligible for any
route until a human approves it. Publishing a model-callable verb on the
strength of a data file nobody reviewed is precisely what the review gate is
for, and a pack is a data file nobody reviewed.

DORMANT UNTIL THE PROVIDER IS PRESENT. A pack names the provider it maps, and
is applied only where a connection for that provider actually exists. So the
Opbox pack ships inside every Boltrig and does nothing at all until an Opbox
door is registered, which is presence rather than a flag (decision 0035) and is
what lets one image serve a Boltrig-only box and an Opbox box unchanged.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

from boltrig.models.capability_routing import parse_capability_ref

PACKS_DIR = pathlib.Path(__file__).resolve().parent / "packs"


class MappingPackError(ValueError):
    """A pack is not exact, versioned, and about one provider."""


@dataclass(frozen=True)
class Mapping:
    operation_id: str
    capability_id: str
    capability_version: int


@dataclass(frozen=True)
class MappingPack:
    name: str
    version: int
    provider: str
    mappings: tuple[Mapping, ...]

    def by_operation(self) -> dict[str, Mapping]:
        return {m.operation_id: m for m in self.mappings}


def _require(doc: dict, key: str, kind: type):
    value = doc.get(key)
    if not isinstance(value, kind) or (kind is str and not value):
        raise MappingPackError(f"pack field {key!r} must be a non-empty {kind.__name__}")
    return value


def parse_pack(doc: object, *, origin: str = "<memory>") -> MappingPack:
    """Validate one pack document. Fail-closed: a malformed pack is never partially applied.

    Half-applying a pack would publish some of a provider's operations under
    canonical names and silently leave the rest unmapped, which reads exactly
    like a provider that only implements half a domain.
    """
    if not isinstance(doc, dict):
        raise MappingPackError(f"{origin}: a pack is a mapping document")
    name = _require(doc, "pack", str)
    version = _require(doc, "version", int)
    provider = _require(doc, "provider", str)
    raw = doc.get("mappings")
    if not isinstance(raw, list) or not raw:
        raise MappingPackError(f"{origin}: a pack declares at least one mapping")

    mappings: list[Mapping] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise MappingPackError(f"{origin}: each mapping is a mapping document")
        operation = _require(entry, "operation", str)
        implements = _require(entry, "implements", str)
        capability_id, pinned = parse_capability_ref(implements)
        if pinned is None:
            # A pack pins deliberately. Unpinned means "the tenant's newest live
            # version", so an unpinned pack would silently re-target itself when
            # a new capability version appears - a curated claim about a
            # contract it has never seen.
            raise MappingPackError(
                f"{origin}: {operation!r} must pin a capability version, e.g. matter.open@1"
            )
        if operation in seen:
            raise MappingPackError(f"{origin}: {operation!r} is mapped twice")
        seen.add(operation)
        mappings.append(Mapping(operation, capability_id, pinned))
    return MappingPack(name, version, provider, tuple(mappings))


def load_packs(directory: pathlib.Path | None = None) -> dict[str, MappingPack]:
    """Every shipped pack, keyed by the provider it maps.

    One pack per provider: two packs claiming the same provider is a conflict
    nobody would notice at runtime, because whichever loaded last would decide
    the mappings and the other would simply never apply.
    """
    base = PACKS_DIR if directory is None else directory
    packs: dict[str, MappingPack] = {}
    if not base.is_dir():
        return packs
    for path in sorted(base.glob("*.yaml")):
        pack = parse_pack(yaml.safe_load(path.read_text(encoding="utf-8")), origin=str(path))
        if pack.provider in packs:
            raise MappingPackError(
                f"{path}: provider {pack.provider!r} is already mapped by "
                f"pack {packs[pack.provider].name!r}"
            )
        packs[pack.provider] = pack
    return packs
