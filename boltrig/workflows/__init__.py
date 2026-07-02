"""The workflow library: precreated, generated and learned process definitions.

Workflows are data (P1). This package selects and synthesises
:class:`boltrig.models.WorkflowDefinition` records; durable execution is Hatchet
(reached through the ``trigger`` seam).
"""

from __future__ import annotations

from .generator import (
    generate_workflow,
    generate_workflow_reasoned,
    learn_from_success,
    schedule_spec,
    select_or_generate_workflow,
)
from .library import WorkflowLibrary

__all__ = [
    "WorkflowLibrary",
    "generate_workflow",
    "generate_workflow_reasoned",
    "learn_from_success",
    "schedule_spec",
    "select_or_generate_workflow",
]
