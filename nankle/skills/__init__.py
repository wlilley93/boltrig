"""The skill library: YAML data parsed into :class:`nankle.models.Skill`.

Skills are data, not code (P1). This package only parses, validates, loads and
resolves them; the fleet spawner (``nankle.fleet.spawn``) is the consumer.
"""

from __future__ import annotations

from .loader import (
    SkillNotFound,
    load_skills_dir,
    resolve_skill,
    select_locale,
)
from .schema import DEFAULT_LOCALE, SkillValidationError, parse_skill

__all__ = [
    "DEFAULT_LOCALE",
    "SkillNotFound",
    "SkillValidationError",
    "load_skills_dir",
    "parse_skill",
    "resolve_skill",
    "select_locale",
]
