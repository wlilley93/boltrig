"""Sleep distillation (decision 0023): corpus derivation and promotion gates.

This package sits beside ``fleet/`` and imports downward only (``models``,
``store`` contracts, ``kernel.pii``). Nothing under ``kernel/`` or ``models/``
may import from here - the kernel's one distillation surface is the ``distill``
adapter's verbs, resolved like any other integration.
"""

from .corpus import (
    Corpus,
    CorpusDataClassRefused,
    CorpusTenantMismatch,
    PrefRecord,
    SftRecord,
    build_corpus,
)
from .corpus_io import corpus_jsonl_lines
from .gate import CaseScore, GateVerdict, craft_verdict, register_verdict

__all__ = [
    "CaseScore",
    "Corpus",
    "CorpusDataClassRefused",
    "CorpusTenantMismatch",
    "GateVerdict",
    "PrefRecord",
    "SftRecord",
    "build_corpus",
    "corpus_jsonl_lines",
    "craft_verdict",
    "register_verdict",
]
