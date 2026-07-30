"""Skill Studio route composition."""

from __future__ import annotations

from .skill_read_routes import register_skill_read_routes
from .skill_write_routes import register_skill_write_routes


def register(app, P, K) -> None:
    register_skill_read_routes(app, P, K)
    register_skill_write_routes(app, P, K)
