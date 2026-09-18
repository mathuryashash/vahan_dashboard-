FROM python:3.12-slim

WORKDIR /app

# tesseract-ocr: needed at request time by the live maker/fuel query
# endpoint (app/services/live_scrape_service.py) to solve the new
# analytics.parivahan.gov.in site's CAPTCHA -- the batch backfill scripts
# only ever ran outside Docker on a machine with Tesseract installed
# natively, but this on-demand endpoint runs inside this container.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scraper/ ./scraper/
COPY data/reference/ ./data/reference/

EXPOSE 8020

# --workers 1 is stated, not left to uvicorn's default, because three things
# in this app are only correct with exactly one process -- see "Deployment
# constraints" in README.md, and the startup guard in app/main.py:
#   1. app/core/rate_limit.py's LoginRateLimiter counts failed logins in
#      process memory. N workers = N x 5 guesses per window per account.
#   2. The TTLCache instances in app/api/v1/endpoints/* are module-level, so
#      N workers means N caches and the same query can answer two different
#      numbers depending on which worker takes the request.
#   3. DB_POOL_SIZE + DB_MAX_OVERFLOW = 60 connections PER PROCESS against
#      Postgres max_connections=100, which the scrapers already draw on
#      (see scraper/pool_sizing.py). Two workers is 120 and the excess
#      fails to connect rather than queueing.
# --no-access-log: the request middleware in app/main.py emits one line per
# request carrying the request id; uvicorn's own access logger sets
# propagate=False and its own formatter, so it can never carry that id and
# would just duplicate every line.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1", "--no-access-log"]
