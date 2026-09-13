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
