"""Refuse to start multi-worker, because three things here are only correct
with exactly one process.

1. app/core/rate_limit.py's LoginRateLimiter counts failed logins in process
   memory. N workers means N x 5 password guesses per window against
   accounts whose emails are public.
2. The TTLCache instances in app/api/v1/endpoints/* are module-level. N
   workers means N independent caches, so the same query can return two
   different numbers depending on which worker answers.
3. DB_POOL_SIZE + DB_MAX_OVERFLOW is 60 connections PER PROCESS against
   Postgres max_connections=100, which the scraper processes already draw
   on (scraper/pool_sizing.py). Two workers is 120, and the excess does not
   queue -- it fails to connect.

WHAT THIS CANNOT DETECT. A worker cannot reliably count its siblings.
Uvicorn's supervisor hands the child no worker count and no registry;
Gunicorn exposes `workers` to arbiter hooks, not to application code.
Scanning /proc for processes with a matching argv is a guess that breaks
under `docker exec`, under a second container on the same host, and under
any supervisor that rewrites the command line. So this reads DECLARED
intent, and it is blind to N separate containers or VPSes each running one
worker behind a load balancer -- which breaks all three invariants
identically. That case is covered by the README and by nothing else.

The escape hatch is ALLOW_MULTI_WORKER=true, for whoever has actually moved
the limiter and caches to a shared store and divided the pool sizes.
"""
import logging
import os
import sys

logger = logging.getLogger("worker_guard")

_WORKER_FLAGS = ("--workers", "-w")


def declared_worker_count(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    """How many workers this process was ASKED for. 1 when nothing says otherwise.

    Never raises: a guard that crashes the API because it could not parse a
    command line is worse than the misconfiguration it is looking for.
    """
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env

    try:
        # Precedence mirrors uvicorn's own: an explicit --workers wins, and
        # WEB_CONCURRENCY is only consulted when no flag was given
        # (uvicorn/config.py applies the env fallback `if workers is None`).
        # Taking max() of both instead refused to boot on the perfectly
        # correct combination this repo's own Dockerfile produces --
        # `--workers 1` with a stray WEB_CONCURRENCY=4 in the environment,
        # which uvicorn resolves to one worker.
        cli = _cli_worker_count(argv)
        if cli is not None:
            return cli

        raw = env.get("WEB_CONCURRENCY", "")
        if raw.strip().isdigit():
            return max(1, int(raw.strip()))

        # Gunicorn's own default is 1 worker, but it is deliberately not used
        # here, and with no explicit count there is nothing to read -- so
        # treat it as something to look at rather than wave through. An
        # explicit --workers under gunicorn is honoured by the branch above.
        if env.get("SERVER_SOFTWARE", "").lower().startswith("gunicorn"):
            return 2
    except (IndexError, ValueError):  # pragma: no cover - defensive
        logger.warning("Could not parse the worker count; assuming 1", exc_info=True)
    return 1


def _cli_worker_count(argv: list[str]) -> int | None:
    """The explicit --workers/-w value, or None if the flag is absent.

    sys.argv survives into uvicorn's spawned children, so this reads the same
    in every worker as in the supervisor. Takes the highest value if the flag
    somehow appears twice, rather than only the first occurrence.
    """
    found: list[int] = []
    for flag in _WORKER_FLAGS:
        for i, arg in enumerate(argv):
            value = None
            if arg == flag and i + 1 < len(argv):
                value = argv[i + 1]
            elif arg.startswith(f"{flag}="):
                value = arg.split("=", 1)[1]
            if value is not None and value.strip().isdigit():
                found.append(int(value.strip()))
    return max(found) if found else None


def assert_single_worker(argv: list[str] | None = None, env: dict[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    if env.get("ALLOW_MULTI_WORKER", "").strip().lower() == "true":
        logger.warning(
            "ALLOW_MULTI_WORKER is set. The login rate limiter and the endpoint TTL "
            "caches keep per-process state, and each worker opens its own "
            "DB_POOL_SIZE + DB_MAX_OVERFLOW connection pool -- make sure those were "
            "actually addressed before relying on this."
        )
        return

    count = declared_worker_count(argv, env)
    if count > 1:
        raise RuntimeError(
            f"This app is configured for {count} workers but is only correct with 1. "
            "The login rate limiter (app/core/rate_limit.py) and the endpoint TTL caches "
            "keep per-process state, and each worker opens its own DB_POOL_SIZE + "
            "DB_MAX_OVERFLOW connection pool against Postgres max_connections. "
            "Run one worker, or set ALLOW_MULTI_WORKER=true once those are shared. "
            "See 'Deployment constraints' in README.md."
        )
