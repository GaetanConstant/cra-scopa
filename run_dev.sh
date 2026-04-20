#!/bin/bash
set -e

trap 'kill 0' EXIT

echo "Starting backend (port 5500)..."
(cd server && uv run uvicorn main:app --reload --port 5500) &

echo "Starting frontend (port 3300)..."
(cd client && npm run dev) &

wait
