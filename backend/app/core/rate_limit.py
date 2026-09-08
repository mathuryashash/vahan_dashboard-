import time


class LoginRateLimiter:
    """In-process fixed-window lockout, keyed by email -- not a general
    rate limiter (see TTLCache for that), just enough to stop unlimited
    online password guessing against a known account (the 3 demo emails
    are public, documented in this repo's own pass.txt). Per-worker state,
    same tradeoff TTLCache already accepts: fine for the single-worker
    deployment this app actually runs as; would need a shared store (Redis)
    if it ever runs multi-worker.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: float = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def check(self, email: str) -> float | None:
        """Returns seconds until unlocked if this email is currently locked
        out, else None."""
        key = email.lower()
        now = time.monotonic()
        attempts = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
        self._failures[key] = attempts
        if len(attempts) >= self.max_attempts:
            return self.window_seconds - (now - attempts[0])
        return None

    def record_failure(self, email: str) -> None:
        key = email.lower()
        self._failures.setdefault(key, []).append(time.monotonic())

    def record_success(self, email: str) -> None:
        self._failures.pop(email.lower(), None)

    def reset(self) -> None:
        self._failures.clear()


login_rate_limiter = LoginRateLimiter()
