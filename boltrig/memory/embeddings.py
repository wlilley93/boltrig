"""Embeddings for the native vector Memory Engine (MEM-ENG-02).

The native vector engine ranks recall by cosine similarity over real vectors, so
it needs an embedder. Two are provided:

  * ``HashingEmbedder`` - the dev/offline reference: a deterministic, dependency-
    free signed feature-hashing embedder. No model, no network, no provider key -
    so the binding suite exercises true vector recall offline and reproducibly.
    It is not semantic (it captures lexical overlap, not meaning), but it produces
    genuine unit-norm vectors that behave correctly under cosine distance, which
    is exactly what the engine + pgvector's ``<=>`` operator consume.
  * ``Embedder`` - the Protocol the engine depends on. A production deployment
    swaps in a model-backed embedder (a local endpoint for sensitive data, SEC-43)
    behind this same interface; the engine code does not change.

Vectors are L2-normalised, so cosine similarity is a plain dot product and the
distance pgvector stores (``1 - cosine``) is order-preserving.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

# A compact default dimensionality. Large enough that feature-hash collisions are
# rare for normal fact text, small enough to stay fast and well within pgvector's
# hnsw index limit (2000). A deployment may raise this; the engine and the schema
# read the dimension from one place.
DEFAULT_DIM = 256


def _tokens(text: str) -> list[str]:
    """Lexical tokens (alnum runs, lowercased). Order/multiplicity preserved so
    term frequency contributes to the vector."""
    out: list[str] = []
    cur: list[str] = []
    for ch in text or "":
        if ch.isalnum():
            cur.append(ch.lower())
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]:
        """Return a unit-norm vector of length ``dim`` for ``text``."""
        ...


class HashingEmbedder:
    """Deterministic signed feature hashing into a fixed-dim unit vector.

    Each token is hashed (BLAKE2b, NOT Python's salted ``hash``, so results are
    stable across processes) to a bucket index and a sign; term frequencies
    accumulate; the vector is L2-normalised. Two texts that share tokens land
    close under cosine; disjoint texts are near-orthogonal.
    """

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        if dim <= 0:
            raise ValueError("embedding dim must be positive")
        self.dim = dim

    def _bucket(self, token: str) -> tuple[int, float]:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:7], "big") % self.dim
        sign = 1.0 if (h[7] & 1) else -1.0
        return idx, sign

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            idx, sign = self._bucket(tok)
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec  # empty/all-collision text -> zero vector (cosine 0 to all)
        return [x / norm for x in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. For unit-norm inputs this is the dot product; we divide
    by norms anyway so callers may pass un-normalised vectors safely."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)
