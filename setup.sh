#!/bin/bash
set -euo pipefail

echo "Starting VAHAN Dashboard with PostgreSQL..."
docker compose -f docker/docker-compose.yml up --build -d
echo "Dashboard: http://localhost:3000"
echo "API health: http://localhost:8020/health"
echo "PostgreSQL data is stored in the postgres-data Docker volume."
