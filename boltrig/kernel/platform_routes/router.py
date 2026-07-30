"""Router authoring route composition."""

from __future__ import annotations

from .authored_registry_read_routes import register_authored_registry_read_routes
from .authored_registry_write_routes import register_authored_registry_write_routes


def register(app, P, K) -> None:
    register_authored_registry_read_routes(app, P, K)
    register_authored_registry_write_routes(app, P, K)
