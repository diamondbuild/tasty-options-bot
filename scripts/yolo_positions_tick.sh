#!/usr/bin/env bash
# Read-only YOLO position monitor tick for Hermes cron.
# Runs the exit engine over ALL open long-option positions. Never places orders.
set -euo pipefail
cd /opt/data/home/tasty-options-bot
exec .venv/bin/python -m tasty_options_bot.cli yolo-positions
