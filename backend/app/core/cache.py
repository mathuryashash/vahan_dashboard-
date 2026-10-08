import asyncio
import functools
import inspect
import time


class TTLCache:
    """Tiny manual TTL cache for expensive, filter-parameterized aggregate
    queries. Pulled out of the ad-hoc dict+monotonic-timestamp pattern
    already copy-pasted three times (available-years, scrape-progress,
    data-quality) into one reusable place instead of a fourth/fifth copy.

    Callers build the key from the real filter params only -- never include
    a DB session, request, or other per-call object, since those are never
    equal across requests and would defeat caching entirely.
    """
    # Every instance registers itself here so tests can wipe all of them at
    # once (see tests/conftest.py) -- these caches are module-level globals
    # by design (that's what makes them cache across requests in
    # production), which would otherwise leak a cached response from one
    # test's seeded data into a later test that hits the same cache key.
    _all_instances: list = []

    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._store: dict = {}
        TTLCache._all_instances.append(self)

    def get(self, key):
        entry = self._store.get(key)
        if entry is None:
            return None
        value, at = entry
        if time.monotonic() - at >= self.ttl_seconds:
            return None
        return value

    def set(self, key, value) -> None:
        now = time.monotonic()
        # Opportunistic sweep: without this, _store only ever grows -- an
        # expired entry whose key is never queried again (a one-off filter
        # combination, and this cache is explicitly keyed by "expensive,
        # filter-parameterized" params) sits in memory for the life of the
        # process. Bounding this to "entries touched within the last
        # ttl_seconds" instead of "every distinct key ever seen" is what
        # actually keeps a long-running instance's memory use bounded.
        expired = [k for k, (_, at) in self._store.items() if now - at >= self.ttl_seconds]
        for k in expired:
            del self._store[k]
        self._store[key] = (value, now)

    @classmethod
    def clear_all(cls) -> None:
        for instance in cls._all_instances:
            instance._store.clear()


_RETRY = object()


def _flight_key_part(value):
    """Hashable stand-in for one endpoint argument. Sessions/requests are
    skipped by the caller; ORM users are keyed by id + every scope column so
    two tenants can never share a flight."""
    if hasattr(value, "scope_type") and hasattr(value, "id"):
        return ("user", value.id, getattr(value, "role", None), value.scope_type,
                getattr(value, "scope_state_code", None), getattr(value, "scope_rto_code", None),
                getattr(value, "scope_vehicle_category", None))
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def single_flight(fn):
    """Deduplicate CONCURRENT identical calls of an async endpoint.

    The TTL caches only help once the first request has finished; a page that
    fires the same slow aggregate from several components at boot (or several
    users opening the dashboard at once after a cache expiry) used to run it N
    times in parallel, each holding a pooled connection. With this, the first
    caller (the leader) runs the query and every identical call that arrives
    while it is in flight awaits the leader's result instead.

    The key is EVERY resolved argument except DB sessions / requests --
    including the resolved scope dependencies -- so it can never be wider
    than the cache key of the endpoint it wraps. If the leader is cancelled
    (client disconnect), followers retry on their own session rather than
    inheriting the cancellation; a leader exception propagates to followers
    (the same query would fail the same way).
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.requests import Request

    inflight: dict = {}
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        bound = sig.bind_partial(*args, **kwargs)
        key = tuple(
            (name, _flight_key_part(v)) for name, v in sorted(bound.arguments.items())
            if not isinstance(v, (AsyncSession, Request))
        )
        while True:
            fut = inflight.get(key)
            if fut is None:
                break
            result = await asyncio.shield(fut)
            if result is not _RETRY:
                return result
        fut = asyncio.get_running_loop().create_future()
        # Mark exceptions as retrieved when nobody else was waiting.
        fut.add_done_callback(lambda f: f.cancelled() or f.exception())
        inflight[key] = fut
        try:
            result = await fn(*args, **kwargs)
        except asyncio.CancelledError:
            fut.set_result(_RETRY)
            raise
        except BaseException as exc:
            fut.set_exception(exc)
            raise
        else:
            fut.set_result(result)
            return result
        finally:
            if inflight.get(key) is fut:
                del inflight[key]

    wrapper._single_flight_inflight = inflight  # for tests
    return wrapper
