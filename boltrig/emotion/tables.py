"""Load the emotion tables from ``libraries/emotion`` into engine dataclasses (EMO-5).

The runtime model is data, never code: ``model.yaml`` (emotions and needs),
``appraisals.yaml`` (appraisal kind -> deltas) and ``event_map.yaml`` (relay
event -> appraisal kind rules) are parsed with ``yaml.safe_load`` and validated
into frozen dataclasses. ANY failure (missing directory, missing file, bad
shape, non-numeric value) returns ``None`` so the feature stays off; the
emotion channel is cosmetic and must never break a boot (P9).

The directory search mirrors the bootstrap skills loader: the container path
first, then the working-directory path, then the repo checkout relative to
this module. ``BOLTRIG_EMOTION_TEMPO`` overrides the model's tempo (invalid or
non-positive values are ignored).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from boltrig.emotion.engine import Appraisal, EmotionModel

_TABLE_DIR_CANDIDATES = ("/app/libraries/emotion", "libraries/emotion")
_TEMPO_ENV = "BOLTRIG_EMOTION_TEMPO"


@dataclass(frozen=True)
class EventRule:
    """One relay-event matching rule; the first matching rule wins.

    ``type`` must equal the event's ``type``; every ``where`` field must equal
    its value; every ``where_not`` field must NOT equal its value; every
    ``has`` field must be present and truthy. A match fires the ``appraise``
    kind at ``intensity``, rate-limited per (tenant, kind) by ``throttle_s``.
    """

    type: str
    where: Mapping[str, object] = field(default_factory=dict)
    where_not: Mapping[str, object] = field(default_factory=dict)
    has: tuple[str, ...] = ()
    appraise: str = ""
    intensity: float = 0.0
    throttle_s: float = 0.0


def _num(value: object) -> float:
    """A finite number from YAML, rejecting bools and anything non-numeric."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"expected a number, got {type(value).__name__}")


def _float_map(value: object) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected a mapping of name -> number")
    return {str(name): _num(delta) for name, delta in value.items()}


def _find_tables_dir(root: Path | None) -> Path | None:
    if root is not None:
        return root if root.is_dir() else None
    repo_local = Path(__file__).resolve().parents[2] / "libraries" / "emotion"
    for candidate in (*(Path(p) for p in _TABLE_DIR_CANDIDATES), repo_local):
        if candidate.is_dir():
            return candidate
    return None


def _tempo(default: float) -> float:
    """The model tempo, with the env override applied when it parses positive."""
    raw = os.environ.get(_TEMPO_ENV, "").strip()
    if not raw:
        return default
    try:
        override = float(raw)
    except ValueError:
        return default
    return override if override > 0.0 else default


def _parse_appraisals(doc: object) -> dict[str, Appraisal]:
    if not isinstance(doc, dict):
        raise ValueError("appraisals.yaml must be a mapping of kind -> spec")
    out: dict[str, Appraisal] = {}
    for kind, spec in doc.items():
        if not isinstance(spec, dict):
            raise ValueError(f"appraisal '{kind}' must be a mapping")
        out[str(kind)] = Appraisal(
            emotions=_float_map(spec.get("emotions")),
            needs=_float_map(spec.get("needs")),
            tension=_num(spec.get("tension", 0.0)),
        )
    return out


def _parse_model(doc: object, appraisals: Mapping[str, Appraisal]) -> EmotionModel:
    if not isinstance(doc, dict):
        raise ValueError("model.yaml must be a mapping")
    emotions = doc.get("emotions")
    needs = doc.get("needs")
    if not isinstance(emotions, dict) or not isinstance(needs, dict):
        raise ValueError("model.yaml needs 'emotions' and 'needs' mappings")
    baselines: dict[str, float] = {}
    half_lives_h: dict[str, float] = {}
    for name, spec in emotions.items():
        if not isinstance(spec, dict):
            raise ValueError(f"emotion '{name}' must be a mapping")
        baselines[str(name)] = _num(spec.get("baseline"))
        half_lives_h[str(name)] = _num(spec.get("half_life_h"))
    need_defaults: dict[str, float] = {}
    need_decay_h: dict[str, float] = {}
    for name, spec in needs.items():
        if not isinstance(spec, dict):
            raise ValueError(f"need '{name}' must be a mapping")
        need_defaults[str(name)] = _num(spec.get("default"))
        need_decay_h[str(name)] = _num(spec.get("decay_h"))
    return EmotionModel(
        baselines=baselines,
        half_lives_h=half_lives_h,
        need_defaults=need_defaults,
        need_decay_h=need_decay_h,
        appraisals=appraisals,
        tempo=_tempo(_num(doc.get("tempo", 60.0))),
    )


def _parse_rules(doc: object) -> list[EventRule]:
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise ValueError("event_map.yaml must be a mapping with a 'rules' list")
    rules: list[EventRule] = []
    for raw in doc["rules"]:
        if not isinstance(raw, dict):
            raise ValueError("each rule must be a mapping")
        where = raw.get("where") or {}
        where_not = raw.get("where_not") or {}
        has = raw.get("has") or []
        if not isinstance(where, dict) or not isinstance(where_not, dict):
            raise ValueError("'where'/'where_not' must be mappings")
        if not isinstance(has, list):
            raise ValueError("'has' must be a list of field names")
        rules.append(
            EventRule(
                type=str(raw["type"]),
                where={str(k): v for k, v in where.items()},
                where_not={str(k): v for k, v in where_not.items()},
                has=tuple(str(f) for f in has),
                appraise=str(raw["appraise"]),
                intensity=_num(raw["intensity"]),
                throttle_s=_num(raw.get("throttle_s", 0.0)),
            )
        )
    return rules


def load_emotion_tables(
    root: Path | None = None,
) -> tuple[EmotionModel, list[EventRule]] | None:
    """Load and validate the three emotion YAML tables, or ``None`` on ANY failure.

    ``root`` pins the table directory (tests); otherwise the well-known
    candidates are searched. A ``None`` return means the emotion feature stays
    off; it never raises (P9).
    """
    try:
        base = _find_tables_dir(root)
        if base is None:
            return None
        model_doc = yaml.safe_load((base / "model.yaml").read_text(encoding="utf-8"))
        appraisals_doc = yaml.safe_load((base / "appraisals.yaml").read_text(encoding="utf-8"))
        map_doc = yaml.safe_load((base / "event_map.yaml").read_text(encoding="utf-8"))
        model = _parse_model(model_doc, _parse_appraisals(appraisals_doc))
        return model, _parse_rules(map_doc)
    except Exception:  # noqa: BLE001 - P9: any load failure keeps the feature off
        return None
