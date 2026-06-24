#!/usr/bin/env bash
# Start FastAPI backend from project root
cd "$(dirname "$0")/.."
exec uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
