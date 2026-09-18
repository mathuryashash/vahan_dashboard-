"""Per-request correlation id, so one failing request can be followed across
every log line it produced.

Without this, a 500 in production gives you a traceback and no way to tell
which of the ~8 concurrent aggregate queries an Overview page load fired was
the one that died, or which user saw it. With it, every line from a request
carries the same short id, and the response carries it too -- so a screenshot
from a demo maps to a specific set of log lines.

Deliberately a ContextVar rather than a header read at each logging site:
the id has to reach code that has no idea an HTTP request exists (services,
query builders, SQLAlchemy event hooks) without threading a parameter
through all of it.
"""
import logging
import re
import uuid
from contextvars import ContextVar

# "-" rather than "" so a line logged outside any request (startup,
# migrations, the scheduler loop) still lines up in the same column.
NO_REQUEST = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST)

# A client may supply its own id so a trace can span the browser and the API,
# but it goes straight into log lines -- so it is validated, not trusted. A
# newline here would let a caller forge entire log entries ("log injection");
# length is capped so one request cannot bloat every line it touches.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_request_id(supplied: str | None = None) -> str:
    """The client's id if it is safe to echo, otherwise a fresh one."""
    if supplied and _SAFE_REQUEST_ID.match(supplied):
        return supplied
    # 12 hex chars: enough to be unique across a day of traffic on one
    # instance, short enough to stay readable at the front of every line.
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Puts `request_id` on every record so the format string can use it.

    A filter, not a custom Formatter: records reaching the root handler come
    from everywhere (uvicorn, sqlalchemy, our own modules), and only a filter
    guarantees the attribute exists on all of them. Without it, any record
    logged outside a request raises `KeyError: 'request_id'` inside logging
    itself -- which surfaces as a mangled traceback on stderr rather than as
    the log line you were trying to read.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        return True
