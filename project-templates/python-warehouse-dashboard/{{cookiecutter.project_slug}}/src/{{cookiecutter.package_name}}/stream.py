"""Compressed SSE responses and the wake-up hub read streams block on.

Starlette's GZipMiddleware deliberately skips text/event-stream, so the
stream is compressed here, one flush per event. The compressor keeps its
window across events, which is what makes fat morphs cheap: the second
render of a 20 KB region is mostly back-references to the first.
"""

from __future__ import annotations

import asyncio
import contextlib
import zlib
from collections import defaultdict
from collections.abc import AsyncIterator, Hashable, Iterator

import brotli
from starlette.requests import Request
from starlette.responses import StreamingResponse

from .metrics import Collector


class Hub:
    """Keyed broadcast. Watchers block on an Event; notify sets them.

    Coalescing is correct: a watcher re-reads current state when it wakes,
    so a duplicate wake that gets dropped is never a lost update.
    """

    def __init__(self) -> None:
        self._watchers: dict[Hashable, set[asyncio.Event]] = defaultdict(set)

    @contextlib.contextmanager
    def watch(self, key: Hashable) -> Iterator[asyncio.Event]:
        changed = asyncio.Event()
        self._watchers[key].add(changed)
        try:
            yield changed
        finally:
            self._watchers[key].discard(changed)
            if not self._watchers[key]:
                del self._watchers[key]

    def notify(self, key: Hashable) -> None:
        for changed in self._watchers.get(key, ()):
            changed.set()

    def notify_all(self) -> None:
        for watchers in self._watchers.values():
            for changed in watchers:
                changed.set()


class _Identity:
    encoding = None

    def encode(self, data: bytes) -> bytes:
        return data


class _Brotli:
    encoding = "br"

    def __init__(self) -> None:
        # One compressor lives as long as its stream, so its state is paid
        # per connected client. Measured with one process per setting:
        # q5/lgwin22 ~1.5 MB per stream, q3/lgwin18 ~350 KB, and both shrink a
        # repeat render of a 16 KB region to 14 bytes. A 256 KB window still
        # lets any region under ~128 KB back-reference its previous render.
        self._c = brotli.Compressor(mode=brotli.MODE_TEXT, quality=3, lgwin=18)

    def encode(self, data: bytes) -> bytes:
        return self._c.process(data) + self._c.flush()


class _Gzip:
    encoding = "gzip"

    def __init__(self) -> None:
        self._c = zlib.compressobj(6, zlib.DEFLATED, 31)

    def encode(self, data: bytes) -> bytes:
        return self._c.compress(data) + self._c.flush(zlib.Z_SYNC_FLUSH)


def _negotiate(accept_encoding: str) -> _Identity | _Brotli | _Gzip:
    offered = {part.split(";")[0].strip() for part in accept_encoding.lower().split(",")}
    if "br" in offered:
        return _Brotli()
    if "gzip" in offered:
        return _Gzip()
    return _Identity()


def sse(request: Request, events: AsyncIterator[str], collector: Collector) -> StreamingResponse:
    """Wrap an event generator as a compressed, counted SSE response.

    Starlette cancels the body iterator when the client disconnects, which
    runs the generator's `finally` and unregisters its watcher.
    """
    encoder = _negotiate(request.headers.get("accept-encoding", ""))

    async def body() -> AsyncIterator[bytes]:
        collector.open_streams += 1
        try:
            async for event in events:
                raw = event.encode()
                wire = encoder.encode(raw)
                collector.patch(len(raw), len(wire))
                yield wire
        finally:
            collector.open_streams -= 1

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Vary": "Accept-Encoding"}
    if encoder.encoding:
        headers["Content-Encoding"] = encoder.encoding
    return StreamingResponse(body(), media_type="text/event-stream", headers=headers)
