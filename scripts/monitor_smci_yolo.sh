#!/usr/bin/env bash
# Hourly read-only SMCI YOLO position monitor (cron wrapper).
cd /opt/data/home/tasty-options-bot || exit 1
exec .venv/bin/python scripts/monitor_smci_yolo.py
