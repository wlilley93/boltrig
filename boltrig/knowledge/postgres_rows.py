"""asyncpg row conversion helpers for the Knowledge repository."""

from __future__ import annotations

import json
from typing import Any

from .models import Asset, ProjectionStatus, Provider, SearchHit, Segment, UploadSession


def upload(row) -> UploadSession:
    return UploadSession(**{key: row[key] for key in UploadSession.__dataclass_fields__})


def asset(row) -> Asset:
    return Asset(**{key: row[key] for key in Asset.__dataclass_fields__})


def segment(row) -> Segment:
    values = {key: row[key] for key in Segment.__dataclass_fields__}
    values["locator"] = json_value(values["locator"])
    return Segment(**values)


def provider(row) -> Provider:
    values = {key: row[key] for key in Provider.__dataclass_fields__}
    values["config"] = json_value(values["config"])
    return Provider(**values)


def projection(row) -> ProjectionStatus:
    return ProjectionStatus(**{key: row[key] for key in ProjectionStatus.__dataclass_fields__})


def asset_public(row) -> dict[str, Any]:
    return {
        "id": row["id"], "title": row["title"], "filename": row["filename"],
        "asset_type": row["asset_type"], "workspace_id": row["workspace_id"],
        "revision_id": row["current_revision_id"], "source_kind": row["source_kind"],
        "source_ref": row["source_ref"], "segment_count": row["segment_count"],
        "created_at": row["created_at"].isoformat(),
    }


def hit(row) -> SearchHit:
    return SearchHit(
        asset_id=row["asset_id"], revision_id=row["current_revision_id"],
        segment_id=row["segment_id"], title=row["title"], filename=row["filename"],
        text=row["text"], locator=json_value(row["locator"]),
        score=float(row["score"] or 0), content_hash=row["content_hash"],
        source_kind=row["source_kind"], source_ref=row["source_ref"],
    )


def vector(values) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in values) + "]"


def parse_vector(value) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return [float(item) for item in str(value).strip("[]").split(",") if item]


def json_value(value):
    return json.loads(value) if isinstance(value, str) else dict(value or {})
