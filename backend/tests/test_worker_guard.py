"""The multi-worker guard is a branch, so it gets a check.

Everything here passes argv/env explicitly -- the guard must never be tested
against the real process, or the test result depends on how pytest was
launched.
"""
import pytest

from app.core.worker_guard import assert_single_worker, declared_worker_count

UVICORN = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]


def test_a_plain_single_worker_command_is_allowed():
    assert declared_worker_count(UVICORN + ["--workers", "1"], {}) == 1
    assert_single_worker(UVICORN + ["--workers", "1"], {})  # must not raise


def test_no_worker_flag_at_all_means_one():
    assert declared_worker_count(UVICORN, {}) == 1
    assert_single_worker(UVICORN, {})


@pytest.mark.parametrize("argv", [
    UVICORN + ["--workers", "4"],
    UVICORN + ["--workers=4"],
    UVICORN + ["-w", "4"],
    UVICORN + ["-w=4"],
])
def test_a_worker_flag_above_one_refuses_to_boot(argv):
    assert declared_worker_count(argv, {}) == 4
    with pytest.raises(RuntimeError, match="only correct with 1"):
        assert_single_worker(argv, {})


def test_web_concurrency_is_honoured():
    """uvicorn --workers and gunicorn workers both default to this, so a
    deployment can go multi-worker without the command line ever changing."""
    assert declared_worker_count(UVICORN, {"WEB_CONCURRENCY": "8"}) == 8
    with pytest.raises(RuntimeError):
        assert_single_worker(UVICORN, {"WEB_CONCURRENCY": "8"})


def test_an_explicit_worker_flag_beats_web_concurrency():
    """uvicorn ignores WEB_CONCURRENCY when --workers is given explicitly
    (its env fallback applies only `if workers is None`). Taking max() of the
    two instead refused to boot on exactly what our own Dockerfile produces:
    `--workers 1` plus a stray WEB_CONCURRENCY from the platform."""
    argv = UVICORN + ["--workers", "1", "--no-access-log"]
    assert declared_worker_count(argv, {"WEB_CONCURRENCY": "4"}) == 1
    assert_single_worker(argv, {"WEB_CONCURRENCY": "4"})  # must not raise

    # ...and the opposite direction still refuses.
    argv = UVICORN + ["--workers", "4"]
    assert declared_worker_count(argv, {"WEB_CONCURRENCY": "1"}) == 4
    with pytest.raises(RuntimeError):
        assert_single_worker(argv, {"WEB_CONCURRENCY": "1"})


def test_an_explicit_single_worker_is_honoured_even_under_gunicorn():
    """Gunicorn is suspect only when it declares nothing -- a deployment that
    explicitly says one worker is telling the truth."""
    argv = UVICORN + ["--workers", "1"]
    assert_single_worker(argv, {"SERVER_SOFTWARE": "gunicorn/23.0.0"})


def test_a_repeated_flag_takes_the_highest_value():
    assert declared_worker_count(UVICORN + ["-w", "1", "--workers", "6"], {}) == 6


def test_gunicorn_is_treated_as_suspect():
    """Gunicorn's own default is one worker, but it is deliberately not used
    here -- its presence means someone changed the process model."""
    with pytest.raises(RuntimeError):
        assert_single_worker(UVICORN, {"SERVER_SOFTWARE": "gunicorn/23.0.0"})


def test_the_escape_hatch_works():
    assert_single_worker(UVICORN + ["--workers", "4"], {"ALLOW_MULTI_WORKER": "true"})


def test_the_escape_hatch_is_not_triggered_by_a_near_miss():
    """Only the literal "true" opts out. "1"/"yes"/"TRUE_" must not, or a
    typo silently disables the guard."""
    for value in ["1", "yes", "TRUE_", "", "false"]:
        with pytest.raises(RuntimeError):
            assert_single_worker(UVICORN + ["--workers", "4"], {"ALLOW_MULTI_WORKER": value})


def test_a_malformed_worker_count_never_breaks_startup():
    """A guard that refuses to boot because it could not parse a command
    line is worse than the misconfiguration it looks for."""
    assert declared_worker_count(UVICORN + ["--workers"], {}) == 1
    assert declared_worker_count(UVICORN + ["--workers", "abc"], {}) == 1
    assert declared_worker_count(UVICORN, {"WEB_CONCURRENCY": "not-a-number"}) == 1
    assert_single_worker(UVICORN + ["--workers"], {})
