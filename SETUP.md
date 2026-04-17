# Project Setup Guide

## Virtual Environment Setup

A Python virtual environment (venv) has been created for this project. Follow these steps to use it:

### 1. Activate the Virtual Environment

```bash
# Navigate to project root
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed

# Activate the virtual environment
source venv/bin/activate
```

**Note**: After activation, your terminal prompt will be prefixed with `(venv)`, indicating the virtual environment is active.

### 2. Verify Installation

To verify that all dependencies are installed correctly:

```bash
# Check pip version
pip --version

# List all installed packages
pip list
```

### 3. Install/Update Dependencies

If you need to install or update dependencies:

```bash
# Install all dependencies from requirements.txt
pip install -r cron/requirements.txt

# Upgrade pip (recommended)
pip install --upgrade pip
```

### 4. Deactivate Virtual Environment

When you're done working, deactivate the virtual environment:

```bash
deactivate
```

---

## Running Scripts with Virtual Environment

### Before running any scripts, make sure to:

1. **Activate the virtual environment**:
   ```bash
   source venv/bin/activate
   ```

2. **Set PYTHONPATH**:
   ```bash
   export PYTHONPATH=.
   ```

3. **Run the script from the project root**:

### Available Scripts

#### 1. Fetch RSS Feeds
```bash
python cron/rss/rss.py
```
This will fetch feeds from configured RSS feed URLs and process them.

#### 2. Clean Old Feeds and Votes
```bash
python cron/rss/clean_rss.py
```
This will remove old feeds and votes based on configured cutoff dates.

#### 3. Fetch Weather Data
```bash
python cron/weather/weather.py
```
This will fetch weather data for upcoming Grand Prix events.

---

## Environment Variables

This project uses environment variables for sensitive configuration. Create a `.env` file in the project root with the following variables:

```
F1_TOKEN=your_f1_token_here
F1_TEST_TOKEN=your_f1_test_token_here
MOTO_GP_TOKEN=your_moto_gp_token_here
```

The `python-dotenv` package will automatically load these variables when the scripts run.

---

## Dependencies

Key dependencies installed in the virtual environment:

- **requests** (2.32.5) - HTTP library
- **feedparser** (6.0.12) - RSS/Atom feed parser
- **beautifulsoup4** (bs4) - HTML/XML parser
- **python-dotenv** (1.2.2) - Environment variable loader
- **loguru** (0.7.3) - Logging library
- **python-dateutil** (2.8.2) - Advanced date parsing (newly added)
- **googletrans-py** (4.0.0) - Translation library
- **firebase-admin** (7.3.0) - Firebase integration
- **playwright** (1.40+) - Browser automation
- **fastf1** (3.8.1) - Formula 1 data library
- **paho-mqtt** (2.0+) - MQTT client

---

## Recent Updates

### Added `python-dateutil` Package

The `python-dateutil` package has been added to support flexible date parsing across multiple formats:

- RFC 2822 format: `Mon, 10 Feb 2026 19:16:24 +0100`
- ISO 8601 format: `2026-02-10T19:16:24+0100`
- Other common formats via automatic detection

**New Functions in `utils.py`**:
- `parse_datetime_string(date_str)` - Parses date strings in multiple formats
- `get_epoch(date_str)` - Converts date string to epoch timestamp

---

## Troubleshooting

### Virtual Environment Not Found
If you get an error about the virtual environment, recreate it:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r cron/requirements.txt
```

### Module Import Errors
Make sure:
1. The virtual environment is activated (check for `(venv)` in prompt)
2. PYTHONPATH is set: `export PYTHONPATH=.`
3. You're running from the project root directory

### Missing Dependencies
Reinstall all dependencies:
```bash
pip install -r cron/requirements.txt --force-reinstall
```

---

## Development Workflow

```bash
# 1. Navigate to project
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed

# 2. Activate venv
source venv/bin/activate

# 3. Set PYTHONPATH
export PYTHONPATH=.

# 4. Run your script
python cron/rss/rss.py

# 5. When done, deactivate
deactivate
```


