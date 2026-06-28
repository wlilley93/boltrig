"""Adapter library: the one interface, the dynamic loader, reference adapters."""

from __future__ import annotations

from .base import Adapter, AdapterError, Credential, ErrorClass, Result, VerbSpec
from .loader import AdapterLoader

__all__ = [
    "Adapter",
    "AdapterError",
    "Credential",
    "ErrorClass",
    "Result",
    "VerbSpec",
    "AdapterLoader",
]
