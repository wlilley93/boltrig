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
from .promotion import WorkflowPromoter, reuse_weight
from .signals import apply_promotion_signal, harvest_reuse_signal

__all__ = [
    "WorkflowLibrary",
    "WorkflowPromoter",
    "apply_promotion_signal",
    "generate_workflow",
    "generate_workflow_reasoned",
    "harvest_reuse_signal",
    "learn_from_success",
    "reuse_weight",
    "schedule_spec",
    "select_or_generate_workflow",
]
