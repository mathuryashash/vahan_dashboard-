#!/bin/bash
set -e
for YEAR in 2024 2025; do
  echo "=== Starting crosstab backfill for $YEAR ==="
  .venv/Scripts/python.exe -m scraper.run_crosstab_scrape --dimension maker_category --year $YEAR > backfill_maker_category_$YEAR.log 2>&1 &
  PID1=$!
  .venv/Scripts/python.exe -m scraper.run_crosstab_scrape --dimension fuel_category --year $YEAR > backfill_fuel_category_$YEAR.log 2>&1 &
  PID2=$!
  .venv/Scripts/python.exe -m scraper.run_crosstab_scrape --dimension maker_fuel --year $YEAR > backfill_maker_fuel_$YEAR.log 2>&1 &
  PID3=$!
  wait $PID1 $PID2 $PID3
  echo "=== Finished crosstab backfill for $YEAR ==="
done
echo "=== ALL CROSSTAB BACKFILL DONE (2024, 2025) ==="
