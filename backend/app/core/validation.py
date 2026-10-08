"""Shared bounds for the numeric query parameters that reach SQL.

Every `year`/`month`/`day` parameter is bound straight into a query against
an INTEGER (int32) column. asyncpg encodes bind parameters client-side, so a
value outside int32 never reaches Postgres as a comparison that returns zero
rows -- it raises OverflowError inside the driver, which surfaces as a
DBAPIError and is caught by app.main's catch-all as a 500. An unauthenticated
shape of "a 500 for a value the API should simply have rejected" is both a
misleading status code and free error-log noise any caller can generate, so
the bound belongs on the parameter, not on the exception handler.

MIN_YEAR is 1947 (independence -- no VAHAN record predates the Republic's
motor-vehicle registry), MAX_YEAR is deliberately generous rather than
"current year": the scrapers write the in-progress financial year, and a
hard current-year ceiling would start rejecting valid requests at each
new-year rollover with no code change.
"""

MIN_YEAR = 1947
MAX_YEAR = 2100
MIN_MONTH = 1
MAX_MONTH = 12
MIN_DAY = 1
MAX_DAY = 31
