"""Redis implementation of the bounded run/conversation event relay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any, AsyncContextManager

from .events import EventRelay
from .redis_event_health import probe_redis_event_capabilities
from .redis_event_lock import redis_conversation_lock


class RedisEventRelay(EventRelay):
    """Bounded multi-replica Redis Stream relay.

    ``XREAD`` from the last replayed ID removes the snapshot/subscription gap.
    """

    def __init__(
        self,
        sync_client: Any,
        async_client: Any,
        *,
        backlog: int = 500,
        max_closed: int = 256,
        namespace: str = "default",
        lock_timeout_s: float = 5.0,
        lock_lease_s: float = 30.0,
        active_lease_s: float = 300.0,
    ) -> None:
        if backlog < 1:
            raise ValueError("backlog must be at least 1")
        if max_closed < 0:
            raise ValueError("max_closed cannot be negative")
        if not namespace or len(namespace) > 64 or not all(
            c.isalnum() or c in "._-" for c in namespace
        ):
            raise ValueError("invalid relay namespace")
        self._sync = sync_client
        self._async = async_client
        self._max = backlog
        self._max_closed = max_closed
        self._prefix = f"boltrig:relay:v1:{namespace}"
        self._lock_timeout_s = max(0.1, min(float(lock_timeout_s), 30.0))
        self._lock_lease_ms = int(
            max(self._lock_timeout_s + 1.0, min(float(lock_lease_s), 300.0))
            * 1000
        )
        self._active_lease_ms = int(max(30.0, min(float(active_lease_s), 86_400.0)) * 1000)
        self._tombstone_lease_ms = 600_000

    @property
    def shared(self) -> bool:
        return True

    async def readiness(self) -> bool:
        return await probe_redis_event_capabilities(self._async, self._prefix)

    async def aclose(self) -> None:
        await self._async.aclose()
        self._sync.close()

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        backlog: int = 500,
        max_closed: int = 256,
        namespace: str = "default",
        timeout_s: float = 2.0,
    ) -> RedisEventRelay:
        if not str(redis_url or "").strip():
            raise ValueError("redis_url is required")
        from redis import Redis
        from redis.asyncio import Redis as AsyncRedis

        return cls(
            Redis.from_url(redis_url, decode_responses=True,
                           socket_connect_timeout=timeout_s, socket_timeout=timeout_s),
            AsyncRedis.from_url(redis_url, decode_responses=True,
                                socket_connect_timeout=timeout_s, socket_timeout=timeout_s),
            backlog=backlog,
            max_closed=max_closed,
            namespace=namespace,
        )

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _digest(self, tenant_id: str, object_id: str) -> str:
        self._key(tenant_id, object_id)
        raw = json.dumps(
            [tenant_id, object_id], ensure_ascii=False, separators=(",", ":")
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    def _stream_keys(self, tenant_id: str, stream_id: str) -> tuple[str, str, str, str]:
        digest = self._digest(tenant_id, stream_id)
        root = f"{self._prefix}:stream:{digest}"
        return root, f"{root}:seq", f"{root}:closed", digest

    def _conversation_keys(
        self, tenant_id: str, conversation_id: str
    ) -> tuple[str, str]:
        digest = self._digest(tenant_id, conversation_id)
        root = f"{self._prefix}:conversation:{digest}"
        return f"{root}:active", f"{root}:lock"

    def _closed_index(self) -> str:
        return f"{self._prefix}:closed"

    def _closed_counter(self) -> str:
        return f"{self._prefix}:closed-seq"

    def _keys_for_digest(self, digest: str) -> tuple[str, str]:
        root = f"{self._prefix}:stream:{digest}"
        return root, f"{root}:seq"

    def _decode_entry(
        self, fields: dict[Any, Any]
    ) -> tuple[str, int | None, dict[str, Any] | None]:
        values = {self._text(key): self._text(value) for key, value in fields.items()}
        kind = values.get("kind", "")
        if kind == "close":
            return kind, None, None
        if kind != "event":
            raise RuntimeError("event_relay_corrupt_entry")
        try:
            seq = int(values["seq"])
            payload = json.loads(values["payload"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("event_relay_corrupt_entry") from exc
        if seq < 1 or not isinstance(payload, dict):
            raise RuntimeError("event_relay_corrupt_entry")
        return kind, seq, payload

    def publish(self, tenant_id: str, stream_id: str, event: dict[str, Any]) -> None:
        stream, seq_key, _closed, _digest = self._stream_keys(tenant_id, stream_id)
        if not isinstance(event, dict):
            raise TypeError("event must be a dictionary")
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        from redis.exceptions import WatchError

        while True:
            with self._sync.pipeline() as pipe:
                try:
                    pipe.watch(seq_key)
                    seq = int(pipe.get(seq_key) or 0) + 1
                    pipe.multi()
                    pipe.set(seq_key, seq)
                    pipe.xadd(
                        stream,
                        {"kind": "event", "seq": str(seq), "payload": payload},
                    )
                    pipe.xtrim(stream, maxlen=self._max, approximate=False)
                    pipe.execute()
                    return
                except WatchError:
                    continue

    def close(self, tenant_id: str, stream_id: str) -> None:
        stream, _seq_key, closed_key, digest = self._stream_keys(
            tenant_id, stream_id
        )
        index, counter = self._closed_index(), self._closed_counter()
        from redis.exceptions import WatchError

        while True:
            with self._sync.pipeline() as pipe:
                try:
                    pipe.watch(closed_key, index, counter)
                    if pipe.exists(closed_key):
                        return
                    closed_seq = int(pipe.get(counter) or 0) + 1
                    existing = int(pipe.zcard(index))
                    evict_count = max(0, existing - self._max_closed + 1)
                    evicted = [
                        self._text(value)
                        for value in pipe.zrange(index, 0, evict_count - 1)
                    ] if evict_count else []
                    if self._max_closed == 0:
                        evicted.append(digest)
                    pipe.multi()
                    pipe.set(counter, closed_seq)
                    pipe.set(closed_key, "1", px=self._tombstone_lease_ms)
                    pipe.xadd(stream, {"kind": "close"})
                    # Keep the entire event window plus the completion marker.
                    pipe.xtrim(stream, maxlen=self._max + 1, approximate=False)
                    pipe.zadd(index, {digest: closed_seq})
                    if evicted:
                        pipe.zrem(index, *evicted)
                        for old_digest in evicted:
                            pipe.delete(*self._keys_for_digest(old_digest))
                    pipe.execute()
                    return
                except WatchError:
                    continue

    def reopen(self, tenant_id: str, stream_id: str) -> None:
        stream, _seq_key, closed_key, digest = self._stream_keys(
            tenant_id, stream_id
        )
        entries = self._sync.xrange(stream)
        close_ids = [
            entry_id
            for entry_id, fields in entries
            if self._decode_entry(fields)[0] == "close"
        ]
        with self._sync.pipeline(transaction=True) as pipe:
            pipe.delete(closed_key)
            pipe.zrem(self._closed_index(), digest)
            if close_ids:
                pipe.xdel(stream, *close_ids)
            pipe.xtrim(stream, maxlen=self._max, approximate=False)
            pipe.execute()

    async def subscribe(
        self,
        tenant_id: str,
        stream_id: str,
        *,
        replay: bool = True,
        since: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for _seq, event in self.subscribe_with_seq(
            tenant_id, stream_id, replay=replay, since=since
        ):
            yield event

    async def subscribe_with_seq(
        self,
        tenant_id: str,
        stream_id: str,
        *,
        replay: bool = True,
        since: int | None = None,
    ) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        stream, _seq_key, closed_key, _digest = self._stream_keys(
            tenant_id, stream_id
        )
        entries = await self._async.xrange(stream)
        last_id = self._text(entries[-1][0]) if entries else "0-0"
        last_seq = since or 0
        complete = False
        for _entry_id, fields in entries:
            kind, seq, event = self._decode_entry(fields)
            if kind == "close":
                complete = True
            elif seq is not None and event is not None:
                if replay and (since is None or seq > since):
                    yield seq, event
                last_seq = max(last_seq, seq)
        if complete or await self._async.exists(closed_key):
            return
        while True:
            batches = await self._async.xread({stream: last_id}, count=100, block=1000)
            if not batches:
                if await self._async.exists(closed_key):
                    return
                continue
            for _name, batch in batches:
                for entry_id, fields in batch:
                    last_id = self._text(entry_id)
                    kind, seq, event = self._decode_entry(fields)
                    if kind == "close":
                        return
                    if seq is not None and event is not None:
                        if seq > last_seq + 1:
                            raise RuntimeError("event_relay_live_cursor_truncated")
                        last_seq = seq
                        yield seq, event

    def forget(self, tenant_id: str, stream_id: str) -> None:
        stream, seq_key, closed_key, digest = self._stream_keys(
            tenant_id, stream_id
        )
        with self._sync.pipeline(transaction=True) as pipe:
            pipe.delete(stream, seq_key, closed_key)
            pipe.zrem(self._closed_index(), digest)
            pipe.execute()

    def snapshot(
        self, tenant_id: str, stream_id: str, *, since: int | None = None
    ) -> list[dict[str, Any]]:
        stream, _seq_key, _closed, _digest = self._stream_keys(
            tenant_id, stream_id
        )
        result: list[dict[str, Any]] = []
        for _entry_id, fields in self._sync.xrange(stream):
            kind, seq, event = self._decode_entry(fields)
            if kind == "event" and seq is not None and event is not None:
                if since is None or seq > since:
                    result.append(event)
        return result

    def max_seq(self, tenant_id: str, stream_id: str) -> int:
        _stream, seq_key, _closed, _digest = self._stream_keys(
            tenant_id, stream_id
        )
        return int(self._sync.get(seq_key) or 0)

    def seq_bounds(self, tenant_id: str, stream_id: str) -> tuple[int | None, int]:
        stream, seq_key, _closed, _digest = self._stream_keys(
            tenant_id, stream_id
        )
        oldest: int | None = None
        for _entry_id, fields in self._sync.xrange(stream):
            kind, seq, _event = self._decode_entry(fields)
            if kind == "event":
                oldest = seq
                break
        return oldest, int(self._sync.get(seq_key) or 0)

    def active_run(self, tenant_id: str, conversation_id: str) -> str | None:
        active_key, _lock_key = self._conversation_keys(tenant_id, conversation_id)
        value = self._sync.get(active_key)
        return None if value is None else self._text(value)

    def set_active_run(
        self, tenant_id: str, conversation_id: str, run_id: str
    ) -> None:
        active_key, _lock_key = self._conversation_keys(tenant_id, conversation_id)
        if not run_id:
            raise ValueError("run_id is required")
        self._sync.set(active_key, run_id, px=self._active_lease_ms)

    def clear_active_run(
        self,
        tenant_id: str,
        conversation_id: str,
        *,
        expected: str | None = None,
    ) -> bool:
        active_key, _lock_key = self._conversation_keys(tenant_id, conversation_id)
        from redis.exceptions import WatchError

        while True:
            with self._sync.pipeline() as pipe:
                try:
                    pipe.watch(active_key)
                    current = pipe.get(active_key)
                    if current is None:
                        return False
                    if expected is not None and self._text(current) != expected:
                        return False
                    pipe.multi()
                    pipe.delete(active_key)
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def refresh_active_run(
        self, tenant_id: str, conversation_id: str, *, expected: str
    ) -> bool:
        active_key, _lock_key = self._conversation_keys(tenant_id, conversation_id)
        from redis.exceptions import WatchError

        while True:
            with self._sync.pipeline() as pipe:
                try:
                    pipe.watch(active_key)
                    current = pipe.get(active_key)
                    if current is None or self._text(current) != expected:
                        return False
                    pipe.multi()
                    pipe.pexpire(active_key, self._active_lease_ms)
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def conversation_lock(
        self, tenant_id: str, conversation_id: str
    ) -> AsyncContextManager[None]:
        _active_key, lock_key = self._conversation_keys(tenant_id, conversation_id)
        return redis_conversation_lock(
            self._async,
            lock_key,
            timeout_s=self._lock_timeout_s,
            lease_ms=self._lock_lease_ms,
        )
