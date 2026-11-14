#!/usr/bin/env python3
"""OTB administrator login limiter — development only."""

import threading
import time


class LoginLimiter:
    """Server-wide, memory-only login attempt limiter."""

    def __init__(
        self,
        max_failures=5,
        window=300,
        lockout=900,
        clock=None
    ):
        if (
            not isinstance(max_failures, int)
            or isinstance(max_failures, bool)
            or max_failures < 1
            or window <= 0
            or lockout <= 0
        ):
            raise ValueError("Invalid rate limit configuration")

        self.max_failures = max_failures
        self.window = window
        self.lockout = lockout
        self.clock = clock or time.monotonic
        self.mutex = threading.Lock()
        self.failures = []
        self.blocked_until = 0.0

    def _refresh(self, now):
        self.failures = [
            attempt for attempt in self.failures
            if now - attempt < self.window
        ]

        if self.blocked_until and now >= self.blocked_until:
            self.blocked_until = 0.0
            self.failures.clear()

    def allowed(self):
        with self.mutex:
            now = self.clock()
            self._refresh(now)
            return now >= self.blocked_until

    def record_failure(self):
        with self.mutex:
            now = self.clock()
            self._refresh(now)

            if now < self.blocked_until:
                return False

            self.failures.append(now)

            if len(self.failures) >= self.max_failures:
                self.blocked_until = now + self.lockout
                return False

            return True

    def record_success(self):
        with self.mutex:
            now = self.clock()
            self._refresh(now)

            # A blocked account cannot be cleared by success.
            if now < self.blocked_until:
                return False

            self.failures.clear()
            return True

    def retry_after(self):
        with self.mutex:
            now = self.clock()
            self._refresh(now)
            return max(0, int(
                self.blocked_until - now + 0.999
            ))
