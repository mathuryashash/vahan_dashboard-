from app.core.cache import TTLCache


def test_get_returns_none_after_ttl_expires():
    cache = TTLCache(ttl_seconds=0.01)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    import time
    time.sleep(0.02)
    assert cache.get("k") is None


def test_set_sweeps_expired_entries_instead_of_leaking_them():
    # Regression test: without the sweep, an expired key that's never read
    # again stays in _store forever -- a real memory leak on a long-running
    # instance for caches keyed by many one-off filter combinations.
    cache = TTLCache(ttl_seconds=0.01)
    cache.set("stale", "v1")
    import time
    time.sleep(0.02)
    assert "stale" in cache._store  # still there until something triggers the sweep

    cache.set("fresh", "v2")

    assert "stale" not in cache._store
    assert "fresh" in cache._store


def test_clear_all_empties_every_registered_instance():
    a = TTLCache(60)
    b = TTLCache(60)
    a.set("x", 1)
    b.set("y", 2)
    TTLCache.clear_all()
    assert a.get("x") is None
    assert b.get("y") is None
