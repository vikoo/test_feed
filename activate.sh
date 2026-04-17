#!/bin/bash

# Quick setup script for the feed project
# This script activates the virtual environment and sets up the Python path

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Activating virtual environment..."
source "$PROJECT_ROOT/venv/bin/activate"

echo "📂 Setting PYTHONPATH..."
export PYTHONPATH="."

echo ""
echo "✅ Environment ready!"
echo ""
echo "Available commands:"
echo "  • python cron/rss/rss.py        - Fetch RSS feeds"
echo "  • python cron/rss/clean_rss.py  - Clean old feeds and votes"
echo "  • python cron/weather/weather.py - Fetch weather data"
echo ""
echo "To deactivate the environment, run: deactivate"
echo ""

