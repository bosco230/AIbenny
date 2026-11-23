"""Passcode login and HMAC-signed visitor sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

COOKIE = "benny_session"
SESSION_DAYS = 30


class Sessions:
    def __init__(self, secret: str, passcode: str) -> None:
        self._secret = secret.encode("utf-8")
        self._passcode = passcode
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def check_passcode(self, attempt: str, client: str) -> bool:
        """Constant-time compare, at most 5 attempts per minute per client."""

        now = time.monotonic()
        window = self._attempts[client]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= 5:
            return False
        window.append(now)
        return bool(self._passcode) and hmac.compare_digest(attempt.encode("utf-8"), self._passcode.encode("utf-8"))

    def too_many_attempts(self, client: str) -> bool:
        now = time.monotonic()
        window = self._attempts[client]
        return sum(1 for t in window if now - t <= 60) >= 5

    def issue(self, visitor_id: str | None = None) -> tuple[str, str]:
        """New (or renewed) visitor id and its signed cookie value."""

        visitor = visitor_id or secrets.token_hex(16)
        expires = int(time.time()) + SESSION_DAYS * 86400
        payload = f"{visitor}.{expires}"
        return visitor, f"{payload}.{self._sign(payload)}"

    def visitor(self, cookie: str | None) -> str | None:
        if not cookie or cookie.count(".") != 2:
            return None
        visitor, expires, signature = cookie.split(".")
        if not hmac.compare_digest(signature, self._sign(f"{visitor}.{expires}")):
            return None
        try:
            if int(expires) < time.time():
                return None
        except ValueError:
            return None
        if len(visitor) != 32 or any(c not in "0123456789abcdef" for c in visitor):
            return None
        return visitor
