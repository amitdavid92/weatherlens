"""Public-demo protection for /api/chat: rate limits, a daily cap, one bounded AI slot, client IPs.

All state is in memory, per process. That is deliberate for a single-instance demo: a restart resets
the counters, which the deployment docs state. Running several instances would need a shared
store such as Redis, so this must not be scaled horizontally as-is.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime

from fastapi import Request

MAX_TRACKED_KEYS = 10_000  # bounds memory if many distinct IPs or sessions appear


class SlidingWindowLimiter:
    """At most `limit` events per `window_seconds` per key. limit <= 0 disables the check."""

    def __init__(self, limit: int, window_seconds: float, *, clock=time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window_seconds, clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record an event. Return None if allowed, or the seconds until a slot frees up."""
        if self.limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            q = self._events.setdefault(key, deque())
            self._events.move_to_end(key)
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(q[0] + self.window - now, 1.0)
            q.append(now)
            while len(self._events) > MAX_TRACKED_KEYS:
                self._events.popitem(last=False)
            return None


class DailyCounter:
    """Application-wide chat requests per UTC day. limit <= 0 disables the check."""

    def __init__(self, limit: int, *, now=lambda: datetime.now(UTC)) -> None:
        self.limit, self._now = limit, now
        self._day, self.count = None, 0
        self._lock = threading.Lock()

    def hit(self) -> bool:
        if self.limit <= 0:
            return True
        with self._lock:
            today = self._now().date()
            if today != self._day:
                self._day, self.count = today, 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True


class ChatSlots:
    """Bounded AI concurrency with a bounded queue. Waiters give up after `queue_timeout`."""

    def __init__(self, concurrent: int, max_waiting: int, queue_timeout: float) -> None:
        self._sem = threading.BoundedSemaphore(max(concurrent, 1))
        self._max_waiting, self._timeout = max(max_waiting, 0), queue_timeout
        self._waiting = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        if self._sem.acquire(blocking=False):
            return True
        with self._lock:
            if self._waiting >= self._max_waiting:
                return False
            self._waiting += 1
        try:
            return self._sem.acquire(timeout=self._timeout)
        finally:
            with self._lock:
                self._waiting -= 1

    def release(self) -> None:
        self._sem.release()


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """The client address as seen by the outermost trusted proxy.

    With N trusted proxies in front of the app (Render, Railway: N=1), the real client is the
    N-th address from the RIGHT of X-Forwarded-For. Entries further left are client-supplied and
    can be spoofed, so they are never used. With N=0 the socket peer is used.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return hops[-trusted_proxy_hops] if len(hops) >= trusted_proxy_hops else peer
