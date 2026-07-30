"""Capability probe for the Redis Stream relay backend."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any


async def probe_redis_event_capabilities(client: Any, prefix: str) -> bool:
    token = secrets.token_hex(8)
    key = f"{prefix}:readiness:{token}"
    stream = f"{key}:stream"
    try:
        async with client.pipeline() as pipe:
            await pipe.watch(key)
            pipe.multi()
            pipe.set(key, "1")
            pipe.xadd(stream, {"probe": "1"})
            await pipe.execute()
        entries = await client.xrange(stream)
        return bool(entries)
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            await client.delete(key, stream)
