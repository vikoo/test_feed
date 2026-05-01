# Feed Management System

A Python project for managing RSS feeds for Formula 1 and Moto GP news, weather data, and race statistics.

## Quick Start

### 1. Activate Virtual Environment

```bash
# Option A: Using the activation script (recommended)
source activate.sh

# Option B: Manual activation
source venv/bin/activate
export PYTHONPATH=.
```

### 2. Run Scripts

All scripts should be run from the project root directory after activating the virtual environment.

#### Fetch RSS Feeds
```bash
python cron/rss/rss.py
```
Fetches the latest feeds from configured RSS feed sources.

#### Clean Old Feeds and Votes
```bash
python cron/rss/clean_rss.py
```
Removes old feeds and votes based on configured cutoff dates.

#### Fetch Weather Data
```bash
python cron/weather/weather.py
```
Fetches weather data for Grand Prix events.

## Setup

For detailed setup instructions, see [SETUP.md](SETUP.md)

### Requirements
- Python 3.8+
- A local virtual environment (`python3 -m venv venv` then `pip install -r cron/requirements.txt`; see [SETUP.md](SETUP.md))
- Dependencies listed in `cron/requirements.txt`

### Environment Variables

Create a `.env` file in the project root:

```
F1_TOKEN=your_token_here
MOTO_GP_TOKEN=your_token_here
```

## Project Structure

Repository root (your clone folder, for example `test_feed/`):

```
├── activate.sh              # Activates venv and sets PYTHONPATH
├── venv/                    # Local only; create per SETUP.md; gitignored
├── cron/
│   ├── rss/                 # RSS feed processing
│   ├── weather/             # Weather data handling
│   ├── f1_live/             # F1 live timing scrape + MQTT publisher
│   ├── strapi_api/          # API integration
│   ├── utils.py             # Shared utilities
│   └── requirements.txt     # Dependencies
├── SETUP.md                 # Detailed setup guide
└── README.md                # This file
```

## Recent Updates

- ✅ Local `venv/` documented and ignored by Git (never commit the virtualenv)
- ✅ Added `python-dateutil` for flexible date parsing
- ✅ Enhanced `fetch_primary_image()` with retry logic and browser headers
- ✅ Created setup documentation and activation script

## Troubleshooting

For issues and troubleshooting steps, refer to [SETUP.md](SETUP.md#troubleshooting)
