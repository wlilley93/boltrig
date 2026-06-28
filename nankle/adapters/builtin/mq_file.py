"""Message-queue and file-share ingest SEAMS (US-ADP-04, US-ADP-06).

These are deliberately thin SEAMS, not finished adapters. Each external driver
(Kafka / RabbitMQ / an OCR engine) is imported LAZILY so the kernel runs without
them installed; when a driver is absent the seam degrades to
:class:`SeamUnavailable`, which a calling adapter maps to
:class:`ErrorClass.UNAVAILABLE` (P9) rather than crashing the kernel.

Two pieces are fully implemented because they need no third-party driver:
:func:`chunk_text` (overlapping fixed-size chunking for downstream embedding)
and the text path of :class:`FileShareIngestSeam`. Everything marked ``SEAM:``
is a wiring point: drop in the concrete client/engine there.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from nankle.adapters.base import AdapterError, ErrorClass


class SeamUnavailable(RuntimeError):
    """A lazily-imported driver/engine for a seam is absent or not wired
    (US-ADP-06). Calling adapters map this to ``ErrorClass.UNAVAILABLE``."""


def _lazy(module_name: str) -> Any:
    """Import a driver on demand; degrade to :class:`SeamUnavailable` if absent."""
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # ImportError and friends
        raise SeamUnavailable(f"driver '{module_name}' is not available") from exc


def as_unavailable(exc: Exception) -> AdapterError:
    """Map a seam failure onto the common taxonomy for a calling adapter."""
    return AdapterError(
        ErrorClass.UNAVAILABLE, str(exc) or "seam unavailable", retryable=True
    )


# --- Kafka seam (US-ADP-04) ---------------------------------------------------
@dataclass
class KafkaSeam:
    """Kafka consume/publish seam. Driver: ``kafka-python`` (``kafka``)."""

    bootstrap_servers: str = "localhost:9092"
    client_id: str = "nankle"

    def publish(self, topic: str, message: bytes, *, key: bytes | None = None) -> None:
        _lazy("kafka")  # degrade cleanly if the driver is missing
        # SEAM: build a KafkaProducer(bootstrap_servers=...) and send(topic, message, key).
        raise SeamUnavailable("kafka publish seam is not wired")

    def consume(
        self, topic: str, *, group_id: str = "nankle", max_messages: int = 10
    ) -> list[bytes]:
        _lazy("kafka")
        # SEAM: build a KafkaConsumer(topic, group_id=...) and poll up to max_messages.
        raise SeamUnavailable("kafka consume seam is not wired")


# --- RabbitMQ seam (US-ADP-04) ------------------------------------------------
@dataclass
class RabbitMqSeam:
    """RabbitMQ consume/publish seam. Driver: ``pika``."""

    url: str = "amqp://guest:guest@localhost:5672/"

    def publish(self, queue: str, message: bytes) -> None:
        _lazy("pika")
        # SEAM: open a BlockingConnection(URLParameters(url)), declare queue, basic_publish.
        raise SeamUnavailable("rabbitmq publish seam is not wired")

    def consume(self, queue: str, *, max_messages: int = 10) -> list[bytes]:
        _lazy("pika")
        # SEAM: open a channel, basic_get up to max_messages, ack on success.
        raise SeamUnavailable("rabbitmq consume seam is not wired")


# --- File-share ingest with OCR + chunking (US-ADP-06) ------------------------
def chunk_text(text: str, *, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping fixed-size chunks for downstream embedding.

    Fully implemented (no driver needed). ``overlap`` carries context across
    chunk boundaries; it is clamped below ``chunk_size``.
    """
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    overlap = max(0, min(overlap, chunk_size - 1))
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        chunks.append(text[start : start + chunk_size])
        start += step
    return chunks


def ocr_extract(data: bytes, *, lang: str = "eng") -> str:
    """OCR seam for scanned/binary documents. Engine: ``pytesseract`` + Pillow."""
    _lazy("pytesseract")
    # SEAM: Image.open(BytesIO(data)); pytesseract.image_to_string(img, lang=lang).
    raise SeamUnavailable("ocr seam is not wired")


@dataclass
class FileShareIngestSeam:
    """File-share ingest: read a document, extract text (OCR seam for binaries),
    and chunk it for indexing (US-ADP-06)."""

    root: str = "."
    chunk_size: int = 1000
    overlap: int = 100
    ocr_enabled: bool = False

    def ingest(self, path: str, *, content: str | bytes | None = None) -> dict[str, Any]:
        if content is None:
            content = self._read(path)
        if isinstance(content, bytes):
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = self._maybe_ocr(content)
        else:
            text = content
        return {
            "path": path,
            "chunks": chunk_text(
                text, chunk_size=self.chunk_size, overlap=self.overlap
            ),
        }

    def _maybe_ocr(self, data: bytes) -> str:
        if not self.ocr_enabled:
            raise SeamUnavailable("binary document requires OCR but ocr_enabled is False")
        return ocr_extract(data)

    @staticmethod
    def _read(path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()
