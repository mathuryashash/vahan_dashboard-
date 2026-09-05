#!/bin/bash
set -e
for YEAR in 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 2009 2008 2007 2006 2005 2004 2003; do
  echo "=== Starting crosstab backfill for $YEAR ==="
  .venv/Scripts/python.exe -m scraper.run_maker_category_scrape --year $YEAR > backfill_maker_category_$YEAR.log 2>&1 &
  PID1=$!
  .venv/Scripts/python.exe -m scraper.run_fuel_category_scrape --year $YEAR > backfill_fuel_category_$YEAR.log 2>&1 &
  PID2=$!
  .venv/Scripts/python.exe -m scraper.run_maker_fuel_scrape --year $YEAR > backfill_maker_fuel_$YEAR.log 2>&1 &
  PID3=$!
  wait $PID1 $PID2 $PID3
  echo "=== Finished crosstab backfill for $YEAR ==="
done
echo "=== ALL CROSSTAB BACKFILL DONE (2003-2023 full history) ==="
