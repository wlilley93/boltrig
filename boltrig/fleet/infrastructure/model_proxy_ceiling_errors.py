"""Shared fail-closed model-proxy ceiling errors."""


class ToolCeilingViolation(ValueError):
    """A model call could not be verified against its admitted ceiling."""


class ModelCeilingViolation(ToolCeilingViolation):
    """A model call did not name the admission-pinned model."""


class ReasoningEffortCeilingViolation(ToolCeilingViolation):
    """A model call did not carry the admission-pinned reasoning effort."""
