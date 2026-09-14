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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
