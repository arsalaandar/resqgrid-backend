"""Limit how many requests are handled at the same time.

Why this exists
---------------
FastAPI runs every synchronous dependency and endpoint in a worker thread, and
a request takes a database connection at its first query and keeps it until
the request ends. When more requests are in flight than the pool has
connections, worker threads pile up waiting for connections while the requests
that already hold a connection wait for a free thread to continue. Nothing can
move until the 30-second pool timeout fires, so throughput drops to a trickle
and almost every request fails. The load tests showed exactly this.

Keeping the number of requests in flight at or below the pool size removes the
situation. Extra requests wait here, in the event loop, which uses no thread
and no connection, and get a quick 503 if the wait is too long.
"""

import asyncio
from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.metrics import HTTP_REQUESTS_SHED, HTTP_REQUESTS_WAITING


class ConcurrencyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_concurrent: int,
        queue_timeout: float,
        exempt_paths: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.max_concurrent = max_concurrent
        self.queue_timeout = queue_timeout
        self.exempt_paths = frozenset(exempt_paths)
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        # A semaphore belongs to one event loop. The server has a single loop;
        # tests create a new one per client, so build a fresh semaphore then.
        loop = asyncio.get_running_loop()

        if self._semaphore is None or self._loop is not loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._loop = loop

        return self._semaphore

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Health checks and metrics must keep answering while the app is busy.
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        semaphore = self._get_semaphore()
        HTTP_REQUESTS_WAITING.inc()

        try:
            async with asyncio.timeout(self.queue_timeout):
                await semaphore.acquire()
        except TimeoutError:
            HTTP_REQUESTS_SHED.inc()
            response = JSONResponse(
                status_code=503,
                content={"detail": "The server is busy. Please try again shortly."},
                headers={"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        finally:
            HTTP_REQUESTS_WAITING.dec()

        try:
            await self.app(scope, receive, send)
        finally:
            semaphore.release()
