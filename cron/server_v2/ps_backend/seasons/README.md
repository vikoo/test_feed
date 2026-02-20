# Quick Start: PS Seasons

## Get Seasons in 30 Seconds

### Basic Usage
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import fetch_all_seasons

seasons = fetch_all_seasons()
# Returns: {'2023': 1, '2024': 2, '2025': 3}
```

---

## Common Tasks

### 1. Get All Seasons
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import fetch_all_seasons

seasons = fetch_all_seasons()
for year, season_id in seasons.items():
    print(f"{year}: {season_id}")
```

### 2. Look Up Season ID by Year
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import (
    fetch_all_seasons,
    get_season_by_year
)

seasons = fetch_all_seasons()
season_2024 = get_season_by_year(2024, seasons)
```

### 3. Display Formatted Table
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import (
    fetch_all_seasons,
    display_seasons
)

seasons = fetch_all_seasons()
display_seasons(seasons)
```

### 4. Error Handling
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import fetch_all_seasons
from cron.server_v2.ps_backend.utils.common_utils import APIError

try:
    seasons = fetch_all_seasons()
except APIError as e:
    print(f"Failed: {e}")
```

### 5. Use with Other Data
```python
from cron.server_v2.ps_backend.seasons.ps_seasons import fetch_all_seasons
from cron.server_v2.ps_backend.utils.common_utils import print_json

seasons = fetch_all_seasons()
print_json(seasons)  # Pretty print
```

---

## Run as Script

```bash
export PYTHONPATH=.
python cron/server_v2/ps_backend/seasons/ps_seasons.py
```

---

## Functions Overview

| Function | Returns | Purpose |
|----------|---------|---------|
| `fetch_all_seasons()` | `Dict[str, int]` | Fetch all seasons from API |
| `get_season_by_year(year, dict)` | `Optional[int]` | Get season ID for a year |
| `display_seasons(dict)` | None | Print formatted table |

---

## Return Format

```python
{
    "2023": 1,
    "2024": 2,
    "2025": 3
}
```

---

## Full Documentation

See **PS_SEASONS_GUIDE.md** for comprehensive guide

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Set `export PYTHONPATH=.` |
| `APIError (401)` | Check token in `config.py` |
| `Empty dict` | Check if API is up |

---

## Common Pattern

```python
# Initialize once (single API call)
seasons = fetch_all_seasons()

# Use many times (no API calls)
for year in range(2020, 2025):
    sid = get_season_by_year(year, seasons)
```

---

*For detailed documentation, see PS_SEASONS_GUIDE.md*

