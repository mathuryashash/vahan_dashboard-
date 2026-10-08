"""Per-RTO retry with jittered exponential backoff, plus an opt-in skip-list
for RTOs that keep failing run after run.

Before this, one transient error on an RTO request (a ConnectError, a 5xx, a
half-rendered table that failed _validate_export) dropped that RTO for the
whole run: the state stayed partial and the next 5h run tried once more. A
couple of quick retries recover nearly all of those. Jitter keeps the
concurrent state workers from retrying in lock-step against the same site.

The skip-list is OFF by default (SCRAPER_SKIP_AFTER_FAILED_RUNS=0). When set
to N > 0, an RTO that failed in N consecutive runs (per dimension) is skipped
-- reported, never silently treated as done -- so a permanently broken office
stops costing retries and delay on every run. Its state is reported partial.
State lives in small per-dimension JSON files
(SCRAPER_DATA_DIR/rto_failures.<dimension>.json), never in the database.
A skipped RTO is re-probed every SCRAPER_SKIP_RECHECK_EVERY_RUNS-th run (default
5), so quarantine is not permanent. Delete a file (or one entry) to un-skip.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


RTO_RETRIES = _env_int("SCRAPER_RTO_RETRIES", 2)  # extra attempts after the first
RTO_RETRY_BASE_SECONDS = _env_float("SCRAPER_RTO_RETRY_BASE_SECONDS", 2.0)
RTO_RETRY_MAX_SECONDS = _env_float("SCRAPER_RTO_RETRY_MAX_SECONDS", 30.0)
SKIP_AFTER_FAILED_RUNS = _env_int("SCRAPER_SKIP_AFTER_FAILED_RUNS", 0)  # 0 = off
# A quarantined RTO is re-probed every Nth run it would be skipped (0 = never).
SKIP_RECHECK_EVERY_RUNS = _env_int("SCRAPER_SKIP_RECHECK_EVERY_RUNS", 5)


def backoff_delay(attempt: int, base: float = RTO_RETRY_BASE_SECONDS, cap: float = RTO_RETRY_MAX_SECONDS,
                  rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt)),
    floored at base/2 so a retry never fires instantly."""
    rng = rng or random
    ceiling = min(cap, base * (2 ** attempt))
    return max(base / 2, rng.uniform(0, ceiling))


async def with_retries(fn, *, label: str, retries: int | None = None, no_retry=lambda exc: False,
                       sleep=asyncio.sleep, base: float | None = None, cap: float | None = None):
    """Await fn() up to 1 + retries times. Exceptions for which no_retry(exc)
    is true (e.g. a dead JSF session -- every retry on it would fail the same
    way, and the caller has its own re-authentication path) propagate at once."""
    retries = RTO_RETRIES if retries is None else retries
    base = RTO_RETRY_BASE_SECONDS if base is None else base
    cap = RTO_RETRY_MAX_SECONDS if cap is None else cap
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as exc:
            if no_retry(exc) or attempt == retries:
                raise
            delay = backoff_delay(attempt, base, cap)
            logger.warning("%s: attempt %d/%d failed (%s) -- retrying in %.1fs",
                           label, attempt + 1, retries + 1, exc, delay)
            await sleep(delay)


class RtoFailureTracker:
    """Consecutive failed RUNS per (dimension, rto_code), persisted to JSON.

    A run counts once per RTO no matter how many retries failed inside it;
    any success resets the count. threshold <= 0 disables skipping entirely
    (failures are still recorded so turning it on later has history).

    Persistence is ONE FILE PER DIMENSION (`rto_failures.<dimension>.json`
    next to `path`): run_scraper launches the maker / vehicle_class / fuel
    passes as three concurrent OS processes, and with a single shared file
    each rewrote it from its own in-memory dict -- last writer won and the
    other passes' counts were lost. Each process only ever writes its own
    dimension's file, through a pid+uuid-unique temp name (a shared
    `rto_failures.tmp` also collided across processes). A legacy combined
    `rto_failures.json` is migrated ONCE on load: its entries are merged
    into the per-dimension files (per-dimension values win -- they are
    newer) and the file is renamed to `rto_failures.json.migrated`, so it is
    never read again (it was never rewritten either, so cleared failures
    kept coming back from it on every load).

    Quarantine is not permanent: a skipped RTO is re-probed every
    `recheck_every`-th run it would otherwise be skipped (default
    SCRAPER_SKIP_RECHECK_EVERY_RUNS=5), so an office that recovered can
    `record_success` and leave the list.
    """

    def __init__(self, path: str | os.PathLike | None, threshold: int = SKIP_AFTER_FAILED_RUNS,
                 run_id: str | None = None, recheck_every: int | None = None):
        self.path = Path(path) if path else None
        self.threshold = threshold
        self.recheck_every = SKIP_RECHECK_EVERY_RUNS if recheck_every is None else recheck_every
        self.run_id = run_id or uuid.uuid4().hex
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path:
            for f in sorted(self.path.parent.glob(f"{self.path.stem}.*{self.path.suffix}")):
                try:
                    self._data.update(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    logger.warning("Ignoring unreadable RTO failure file %s", f)
            if self.path.exists():
                self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """Fold the legacy combined file into the per-dimension files, then
        rename it out of the way. Concurrent passes may race here: whoever
        loses the rename just finds the file gone, and every writer merged
        the same legacy entries under per-dimension ones, so nothing is lost."""
        try:
            legacy = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("Legacy RTO failure file %s is unreadable; leaving it in place", self.path)
            return
        dims = set()
        with self._lock:
            for key, entry in legacy.items():
                if ":" not in key:
                    continue
                dims.add(key.split(":", 1)[0])
                self._data.setdefault(key, entry)
            for dim in sorted(dims):
                self._save(dim)
        try:
            self.path.replace(self.path.with_name(self.path.name + ".migrated"))
            logger.info("Migrated legacy %s into per-dimension files (%s)", self.path.name, ", ".join(sorted(dims)))
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Could not rename legacy %s after migrating it", self.path)

    @staticmethod
    def _key(dimension: str, rto_code: str) -> str:
        return f"{dimension}:{rto_code}"

    def dimension_path(self, dimension: str) -> Path | None:
        if not self.path:
            return None
        return self.path.with_name(f"{self.path.stem}.{dimension}{self.path.suffix}")

    def consecutive_failures(self, dimension: str, rto_code: str) -> int:
        return int(self._data.get(self._key(dimension, rto_code), {}).get("failed_runs", 0))

    def should_skip(self, dimension: str, rto_code: str) -> bool:
        """True if the RTO is quarantined for THIS run. Every recheck_every-th
        run that it would be skipped, it is let through once instead (a
        re-probe); idempotent within one run (keyed by run_id)."""
        if not (self.threshold > 0 and self.consecutive_failures(dimension, rto_code) >= self.threshold):
            return False
        if self.recheck_every <= 0:
            return True
        with self._lock:
            entry = self._data[self._key(dimension, rto_code)]
            if entry.get("last_skip_run") != self.run_id:
                entry["skipped_runs"] = int(entry.get("skipped_runs", 0)) + 1
                entry["last_skip_run"] = self.run_id
                self._save(dimension)
            recheck = entry["skipped_runs"] % self.recheck_every == 0
        if recheck:
            logger.info("%s / %s: quarantined, but re-probing this run (every %d runs)",
                        dimension, rto_code, self.recheck_every)
        return not recheck

    def record_failure(self, dimension: str, rto_code: str, error: str = "") -> None:
        with self._lock:
            entry = self._data.setdefault(self._key(dimension, rto_code), {"failed_runs": 0})
            if entry.get("last_run") != self.run_id:
                entry["failed_runs"] = int(entry.get("failed_runs", 0)) + 1
                entry["last_run"] = self.run_id
            entry["last_error"] = error[:300]
            self._save(dimension)

    def record_success(self, dimension: str, rto_code: str) -> None:
        with self._lock:
            if self._data.pop(self._key(dimension, rto_code), None) is not None:
                self._save(dimension)

    def _save(self, dimension: str) -> None:
        target = self.dimension_path(dimension)
        if target is None:
            return
        prefix = f"{dimension}:"
        payload = {k: v for k, v in self._data.items() if k.startswith(prefix)}
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(target)
        except OSError:
            logger.exception("Could not persist RTO failure file %s", target)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


_default_tracker: RtoFailureTracker | None = None


def default_tracker() -> RtoFailureTracker:
    """Process-wide tracker (one scraper run = one process = one run_id)."""
    global _default_tracker
    if _default_tracker is None:
        data_dir = os.environ.get("SCRAPER_DATA_DIR", "./data")
        _default_tracker = RtoFailureTracker(Path(data_dir) / "rto_failures.json")
    return _default_tracker
