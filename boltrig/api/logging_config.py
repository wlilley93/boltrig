"""One declared logging configuration for every boltrig process.

There was none. ``uvicorn boltrig.api.asgi:app`` is how the kernel runs, uvicorn's
own ``LOGGING_CONFIG`` carries no ``root`` key, and ``asgi.py`` never touched
logging - so the root logger kept its default ``WARNING`` level and, decisively,
ZERO handlers. Two things followed, and both were load-bearing in a real incident:

  * every ``log.info``/``log.debug`` in ``boltrig/`` was discarded at
    ``isEnabledFor`` before reaching any handler. Adapter rehydration at boot, for
    one, reports success at INFO - so a boot that wired an adapter and a boot that
    silently skipped it produced byte-identical output: nothing.

  * the WARNINGs that DID survive fell through to ``logging.lastResort``, a bare
    ``StreamHandler`` with no formatter. No timestamp, no level name, no logger
    name. A tenant's agent failed every turn for an hour and emitted eight
    identical unattributed lines with nothing to correlate them against.

Meanwhile ``worker.py`` called ``basicConfig(level=INFO)`` on its own, so the two
containers of one codebase had different visibility and neither was declared.

``BOLTRIG_LOG_LEVEL`` sets the level; the default is INFO because the alternative
is the silence above. Nothing here can leak content (K-20): the format carries a
timestamp, a level name and a LOGGER name, all of which are ours.
"""

from __future__ import annotations

import logging
import os

FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
DEFAULT_LEVEL = "INFO"
ENV_VAR = "BOLTRIG_LOG_LEVEL"


def resolve_level(raw: str | None) -> int:
    """The numeric level for a configured name, falling back to INFO.

    An unreadable value must not silence the process: a typo in an env var is the
    kind of thing that would otherwise reproduce the exact blindness this module
    exists to end, and it would do it quietly.
    """
    name = (raw or DEFAULT_LEVEL).strip().upper()
    level = logging.getLevelNamesMapping().get(name)
    return level if isinstance(level, int) else logging.INFO


def configure_logging(*, force: bool = True) -> int:
    """Install a root handler + formatter for this process. Returns the level set.

    ``force`` overrides any handler a host installed before us (uvicorn installs
    its own on ``uvicorn.*``, not on root), so the root logger is never left in the
    handler-less state that routes through ``logging.lastResort``.
    """
    level = resolve_level(os.environ.get(ENV_VAR))
    logging.basicConfig(level=level, format=FORMAT, force=force)
    logging.getLogger().setLevel(level)
    return level
