"""Request-local Cognee model configuration without ambient secret loading."""

from __future__ import annotations

import importlib.util
import os
import threading
from dataclasses import dataclass
from typing import Any

_COGNEE_IMPORT_LOCK = threading.Lock()
_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_LOCAL_EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True, repr=False, slots=True)
class CogneeRuntimeModel:
    """One request-scoped model route whose credentials are never rendered."""

    model_id: str
    endpoint: str
    api_key: str
    extra_headers: tuple[tuple[str, str], ...] = ()

    def __repr__(self) -> str:
        return "CogneeRuntimeModel(redacted=True)"


def _explicit_config(config_type: Any, **values: Any) -> Any:
    """Construct one request config without invoking BaseSettings sources.

    Cognee's config classes inherit pydantic-settings with ``extra=allow``.
    Their normal constructor absorbs every process environment variable,
    including unrelated credentials, into ``__pydantic_extra__``. These values
    are already validated by Boltrig's exact model/internal-route policy;
    ``model_construct`` applies declared defaults without consulting env or
    dotenv. Rejecting extras is a final tripwire against future API drift.
    """

    config = config_type.model_construct(**values)
    if getattr(config, "__pydantic_extra__", None):
        raise RuntimeError("Cognee request config retained undeclared fields")
    return config


def _require_cognee() -> Any:
    """Import Cognee without allowing python-dotenv to mutate process config."""

    with _COGNEE_IMPORT_LOCK:
        before = dict(os.environ)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        try:
            import cognee
        except ImportError as exc:  # pragma: no cover - monkeypatched by callers
            raise RuntimeError(
                "CogneeEngine requires the 'cognee' package "
                "(pip install 'boltrig[cognee]'). Memory engines are ADOPTED, "
                "not built (MEM-ENG-01)."
            ) from exc
        finally:
            for key in set(os.environ) - set(before):
                os.environ.pop(key, None)
            for key, value in before.items():
                if os.environ.get(key) != value:
                    os.environ[key] = value
    return cognee


def local_embeddings_available() -> bool:
    return importlib.util.find_spec("fastembed") is not None


def runtime_configs(runtime_model: CogneeRuntimeModel | None) -> tuple[Any | None, Any | None]:
    """Build Cognee request-local config without retaining provider plaintext."""

    if runtime_model is None:
        return None, None
    if not local_embeddings_available():
        raise RuntimeError("Cognee local embedding support is unavailable")
    from cognee.infrastructure.databases.vector.embeddings.config import EmbeddingConfig
    from cognee.infrastructure.llm.config import LLMConfig

    llm_config = _explicit_config(
        LLMConfig,
        llm_provider="custom",
        llm_model=runtime_model.model_id,
        llm_endpoint=runtime_model.endpoint,
        llm_api_key=runtime_model.api_key,
        llm_instructor_mode="json_mode",
        llm_args={"extra_headers": dict(runtime_model.extra_headers)},
    )
    embedding_config = _explicit_config(
        EmbeddingConfig,
        embedding_provider="fastembed",
        embedding_model=_LOCAL_EMBEDDING_MODEL,
        embedding_dimensions=_LOCAL_EMBEDDING_DIMENSIONS,
    )
    return llm_config, embedding_config


__all__ = ["CogneeRuntimeModel"]
