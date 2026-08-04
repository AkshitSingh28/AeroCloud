from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

# A login mints a session that stays valid for reads all shift, but actuator
# commands require a PIN entered within the elevation window. The kiosk browser
# never closes, so without this a single unlock would leave the pumps open to
# anyone who walks up for the rest of the day.
DEFAULT_SESSION_SECONDS = 8 * 60 * 60
DEFAULT_ELEVATION_SECONDS = 5 * 60


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{salt.hex()}:{digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    """Constant-time PIN check that treats a malformed record as a failure."""
    try:
        salt_hex, expected_hex = encoded.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    if not salt or not expected_hex:
        return False
    actual = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual.hex(), expected_hex)


@dataclass(slots=True)
class Session:
    expires_at: float
    elevated_until: float


class SessionStore:
    def __init__(
        self,
        lifetime_seconds: int = DEFAULT_SESSION_SECONDS,
        elevation_seconds: int = DEFAULT_ELEVATION_SECONDS,
    ) -> None:
        self._lifetime_seconds = lifetime_seconds
        self._elevation_seconds = elevation_seconds
        self._sessions: dict[str, Session] = {}

    def create(self) -> str:
        self._prune()
        now = time.time()
        token = secrets.token_urlsafe(32)
        self._sessions[token] = Session(
            expires_at=now + self._lifetime_seconds,
            elevated_until=now + self._elevation_seconds,
        )
        return token

    def valid(self, token: str) -> bool:
        session = self._sessions.get(token)
        if session is None:
            return False
        if session.expires_at <= time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def elevated(self, token: str) -> bool:
        if not self.valid(token):
            return False
        return self._sessions[token].elevated_until > time.time()

    def elevation_expires_at(self, token: str) -> float | None:
        session = self._sessions.get(token)
        return session.elevated_until if session else None

    def revoke(self, token: str) -> bool:
        return self._sessions.pop(token, None) is not None

    def _prune(self) -> None:
        now = time.time()
        for token in [token for token, s in self._sessions.items() if s.expires_at <= now]:
            self._sessions.pop(token, None)


class LoginThrottle:
    """Progressive lockout for the operator PIN.

    The PIN is four digits, so an unthrottled endpoint is a five-minute offline
    exercise. Failures are counted per client address and globally, so a
    distributed guess is slowed by the same ladder.
    """

    def __init__(self, threshold: int = 5, base_lockout_seconds: float = 30.0, ceiling: float = 900.0) -> None:
        self.threshold = threshold
        self.base_lockout_seconds = base_lockout_seconds
        self.ceiling = ceiling
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, client: str) -> float:
        now = time.time()
        return max(
            0.0,
            max(self._locked_until.get(client, 0.0), self._locked_until.get("*", 0.0)) - now,
        )

    def record_failure(self, client: str) -> float:
        for key in (client, "*"):
            failures = self._failures.get(key, 0) + 1
            self._failures[key] = failures
            if failures >= self.threshold:
                over = failures - self.threshold
                delay = min(self.base_lockout_seconds * (2**over), self.ceiling)
                self._locked_until[key] = time.time() + delay
        return self.retry_after(client)

    def record_success(self, client: str) -> None:
        for key in (client, "*"):
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
