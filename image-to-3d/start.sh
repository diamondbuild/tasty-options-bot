#!/usr/bin/env bash
# Setup and launch the image-to-3D converter web app
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install -q -e ".[dev]"
fi

echo "Starting server at http://localhost:8000"
.venv/bin/uvicorn img3d.main:app --reload --host 0.0.0.0 --port 8000
