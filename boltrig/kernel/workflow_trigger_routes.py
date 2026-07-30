"""Route facade for governed workflow event-source bindings."""

from .workflow_trigger_author_routes import (
    register_author_workflow_trigger_routes,
)
from .workflow_trigger_delivery import deliver_channel_workflow_triggers
from .workflow_trigger_public_routes import (
    register_public_workflow_trigger_routes,
)


def register_workflow_trigger_routes(app, P, K) -> None:
    register_author_workflow_trigger_routes(app, P, K)
    register_public_workflow_trigger_routes(app, K)


__all__ = [
    "deliver_channel_workflow_triggers",
    "register_workflow_trigger_routes",
]
