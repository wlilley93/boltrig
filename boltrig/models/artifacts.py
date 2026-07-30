"""Immutable, content-addressed artifacts exposed by the Worker read surface."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .base import utcnow

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_ARTIFACT_PAGE = 100
ARTIFACT_PROVENANCE_KINDS = frozenset(
    {"agent", "tool", "workflow", "call", "system"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE = re.compile(
    r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$"
)


def _bounded_ref(label: str, value: str | None) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 256
        or any(not character.isprintable() for character in value)
    ):
        raise ValueError(f"invalid_{label}")


def _required_ref(label: str, value: str) -> None:
    if value is None:
        raise ValueError(f"invalid_{label}")
    _bounded_ref(label, value)


@dataclass(frozen=True)
class ArtifactProvenance:
    kind: str
    actor_ref: str | None = None
    source_ref: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ARTIFACT_PROVENANCE_KINDS:
            raise ValueError("invalid_artifact_provenance_kind")
        for label, value in (
            ("artifact_actor_ref", self.actor_ref),
            ("artifact_source_ref", self.source_ref),
            ("artifact_tool_call_id", self.tool_call_id),
        ):
            _bounded_ref(label, value)
        if not any((self.actor_ref, self.source_ref, self.tool_call_id)):
            raise ValueError("artifact_provenance_reference_required")


@dataclass(frozen=True)
class Artifact:
    id: str
    tenant_id: str
    owner_id: str
    name: str
    digest: str
    media_type: str
    size: int
    revision: int
    provenance: ArtifactProvenance
    workspace_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    work_item_id: str | None = None
    previous_revision_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        for label, value in (
            ("artifact_id", self.id),
            ("artifact_tenant_id", self.tenant_id),
            ("artifact_owner_id", self.owner_id),
        ):
            _required_ref(label, value)
        for optional_label, optional_value in (
            ("artifact_workspace_id", self.workspace_id),
            ("artifact_conversation_id", self.conversation_id),
            ("artifact_run_id", self.run_id),
            ("artifact_work_item_id", self.work_item_id),
            ("artifact_previous_revision_id", self.previous_revision_id),
        ):
            _bounded_ref(optional_label, optional_value)
        if (
            not isinstance(self.name, str)
            or not self.name
            or len(self.name.encode("utf-8")) > 255
            or self.name in {".", ".."}
            or "/" in self.name
            or "\\" in self.name
            or any(not character.isprintable() for character in self.name)
        ):
            raise ValueError("invalid_artifact_name")
        if not isinstance(self.digest, str) or not _SHA256.fullmatch(self.digest):
            raise ValueError("invalid_artifact_digest")
        if (
            not isinstance(self.media_type, str)
            or len(self.media_type) > 127
            or not _MEDIA_TYPE.fullmatch(self.media_type)
        ):
            raise ValueError("invalid_artifact_media_type")
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_ARTIFACT_BYTES
        ):
            raise ValueError("invalid_artifact_size")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or not 1 <= self.revision <= 1_000_000
        ):
            raise ValueError("invalid_artifact_revision")
        if (self.revision == 1) != (self.previous_revision_id is None):
            raise ValueError("invalid_artifact_revision_link")
        if not isinstance(self.provenance, ArtifactProvenance):
            raise TypeError("artifact provenance must be ArtifactProvenance")
        if self.created_at.tzinfo is None:
            raise ValueError("artifact_created_at_must_be_aware")


__all__ = [
    "ARTIFACT_PROVENANCE_KINDS",
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_PAGE",
    "Artifact",
    "ArtifactProvenance",
]
