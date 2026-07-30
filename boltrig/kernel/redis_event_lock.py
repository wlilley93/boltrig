"""Renewed compare-and-delete Redis lock for conversation admission."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from redis.exceptions import WatchError


async def _compare_expire(client: Any, key: str, token: str, lease_ms: int) -> bool:
    while True:
        async with client.pipeline() as pipe:
            try:
                await pipe.watch(key)
                current = await pipe.get(key)
                if current is None or str(current) != token:
                    return False
                pipe.multi()
                pipe.pexpire(key, lease_ms)
                await pipe.execute()
                return True
            except WatchError:
                continue


async def _release(client: Any, key: str, token: str) -> None:
    while True:
        async with client.pipeline() as pipe:
            try:
                await pipe.watch(key)
                current = await pipe.get(key)
                if current is None or str(current) != token:
                    return
                pipe.multi()
                pipe.delete(key)
                await pipe.execute()
                return
            except WatchError:
                continue


@asynccontextmanager
async def redis_conversation_lock(
    client: Any,
    key: str,
    *,
    timeout_s: float,
    lease_ms: int,
) -> AsyncIterator[None]:
    token = secrets.token_hex(16)
    deadline = time.monotonic() + timeout_s
    while not await client.set(key, token, nx=True, px=lease_ms):
        if time.monotonic() >= deadline:
            raise TimeoutError("event_relay_conversation_lock_timeout")
        await asyncio.sleep(0.02)

    lost = asyncio.Event()

    async def renew() -> None:
        interval = max(0.1, lease_ms / 3000)
        while True:
            await asyncio.sleep(interval)
            if not await _compare_expire(client, key, token, lease_ms):
                lost.set()
                return

    renewal = asyncio.create_task(renew(), name="redis-conversation-lock-renewal")
    try:
        yield
        if lost.is_set():
            raise RuntimeError("event_relay_conversation_lock_lost")
    finally:
        renewal.cancel()
        with suppress(asyncio.CancelledError):
            await renewal
        await asyncio.shield(_release(client, key, token))
