import time
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# In production (see frontend/nginx.conf), the browser never reaches uvicorn
# directly -- nginx proxies /api/ to the backend container, so plain
# get_remote_address() would read nginx's own container IP for every
# request (uvicorn isn't started with --proxy-headers, and even if it were,
# that reads X-Forwarded-For, which this nginx config doesn't set -- only
# X-Real-IP, via `proxy_set_header X-Real-IP $remote_addr` in nginx.conf).
# Without this, every user behind the one nginx instance would share a
# single 120/min budget instead of getting their own (code review finding).
# Falls back to get_remote_address for local dev, where there's no proxy in
# front of uvicorn at all and the header is simply absent.
def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or get_remote_address(request)


# Blanket per-IP limit applied to every route via SlowAPIMiddleware (see
# main.py) -- no per-endpoint @limiter.limit() decorators needed. 120/min
# is well above real usage (a full Overview page load fires ~8 aggregation
# calls once, not 120/min), just enough to stop a scripted client hammering
# the 26M-row-scanning endpoints (summary.py kpis/trend/state-ranking,
# categories.py, comparison.py). Kept in this module rather than app.main to
# avoid a circular import: main.py mounts api_router, which imports the
# endpoint modules, which would need this object back from main.py.
limiter = Limiter(key_func=_client_ip, default_limits=["120/minute"])


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
