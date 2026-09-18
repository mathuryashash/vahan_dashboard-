import json
from types import SimpleNamespace

import pytest

from app.main import unhandled_exception_handler


async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_every_response_carries_a_request_id(client):
    """The id is what makes a production failure traceable -- it ties the
    response a user saw to the log lines that request produced."""
    response = await client.get("/health")
    assert response.headers.get("X-Request-ID")


async def test_a_clean_client_supplied_request_id_is_echoed(client):
    """So a trace can span the browser and the API."""
    response = await client.get("/health", headers={"X-Request-ID": "abc-123_XYZ.4"})
    assert response.headers["X-Request-ID"] == "abc-123_XYZ.4"


@pytest.mark.parametrize("hostile", [
    "bad\nINFO forged log line",   # log injection: a newline forges entries
    "x" * 200,                      # unbounded length bloats every line
    "has spaces",
    "semi;colon",
])
async def test_a_hostile_request_id_is_replaced_not_echoed(client, hostile):
    """This header goes straight into log lines, so it is validated, not
    trusted -- otherwise a caller can write whatever they like into the log."""
    response = await client.get("/health", headers={"X-Request-ID": hostile})
    returned = response.headers["X-Request-ID"]
    assert returned != hostile
    assert returned.isalnum() and len(returned) == 12


async def _handle(exc, user_id=None):
    # `state` is always present on a real Starlette Request; the handler reads
    # request.state.user_id to record WHO hit the error.
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/v1/summary/"),
        state=SimpleNamespace(user_id=user_id),
    )
    return await unhandled_exception_handler(request, exc)


async def test_statement_timeout_is_a_gateway_timeout_not_a_crash():
    """A query killed by get_db's statement_timeout is expected, not a bug.

    asyncpg surfaces it as SQLSTATE 57014 on the wrapped DBAPI error; reporting
    that as a 500 would claim we broke when we deliberately gave up on time.
    """
    exc = Exception("statement timeout")
    exc.orig = SimpleNamespace(sqlstate="57014")
    response = await _handle(exc)
    assert response.status_code == 504
    assert "too long" in json.loads(response.body)["detail"]


async def test_every_other_failure_is_still_a_500():
    plain = await _handle(ValueError("boom"))
    assert plain.status_code == 500

    # A different database error must not be mistaken for a timeout.
    other = Exception("unique violation")
    other.orig = SimpleNamespace(sqlstate="23505")
    assert (await _handle(other)).status_code == 500
