# Common Utils Guide

A comprehensive guide to using the shared utility functions in `common_utils.py` for the PS Backend integration.

## Table of Contents

1. [Overview](#overview)
2. [Installation & Setup](#installation--setup)
3. [API Functions](#api-functions)
4. [Data Manipulation Functions](#data-manipulation-functions)
5. [Utility Functions](#utility-functions)
6. [Error Handling](#error-handling)
7. [Examples](#examples)
8. [Best Practices](#best-practices)

---

## Overview

`common_utils.py` provides a collection of utility functions for:
- Making authenticated API requests to the PS Backend
- Safely accessing nested dictionary values
- Formatting dates
- Processing and transforming data
- Pretty-printing JSON

These utilities are designed to be used across different modules in the project to avoid code duplication and ensure consistent API interaction patterns.

---

## Installation & Setup

### Prerequisites

The module requires:
- `requests` library (included in `requirements.txt`)
- Configuration from `cron.ps_backend.utils.config` (BACKEND_URL, TOKEN)

### Import

```python
from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request,
    safe_get,
    format_date,
    print_json,
    chunk_list,
    merge_dicts,
    APIError
)
```

### Configuration

Ensure your `.env` file contains:
```env
BACKEND_URL=https://your-backend-url.com
TOKEN=your_api_token
```

These values are loaded in `cron/ps_backend/utils/config.py`.

---

## API Functions

### `make_ps_api_request()`

Make authenticated requests to the PS Backend API with automatic error handling.

#### Signature
```python
def make_ps_api_request(
    endpoint: str,
    method: str = 'GET',
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    use_auth: bool = True,
    timeout: int = 30
) -> Union[Dict[str, Any], List[Any]]:
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `endpoint` | str | Required | API endpoint path (e.g., `/api/season-types`) |
| `method` | str | `'GET'` | HTTP method: GET, POST, PUT, DELETE, PATCH |
| `params` | Dict | None | Query parameters for the request |
| `data` | Dict | None | Request body data (for POST/PUT/PATCH) |
| `use_auth` | bool | True | Include authentication token in headers |
| `timeout` | int | 30 | Request timeout in seconds |

#### Returns

- `Dict[str, Any]` or `List[Any]`: JSON response from API
- Empty dict `{}` for 204 (No Content) responses

#### Raises

- `APIError`: For HTTP errors, timeouts, connection errors, or invalid JSON

#### Examples

**GET Request with Query Parameters**
```python
# Fetch season types for year 2024
result = make_ps_api_request(
    endpoint='/api/season-types',
    params={'year': 2024}
)
print(result)  # Returns: {'data': [...]}
```

**POST Request to Create Resource**
```python
# Create a new game record
new_game = make_ps_api_request(
    endpoint='/api/games',
    method='POST',
    data={
        'game_id': 12345,
        'home_team': 'LAL',
        'away_team': 'GSW',
        'date': '2024-10-22'
    }
)
print(new_game)
```

**PUT Request to Update Resource**
```python
# Update an existing game
updated = make_ps_api_request(
    endpoint='/api/games/12345',
    method='PUT',
    data={
        'home_team': 'LAL',
        'away_team': 'GSW',
        'final_score': 120
    }
)
```

**DELETE Request**
```python
# Delete a resource
result = make_ps_api_request(
    endpoint='/api/games/12345',
    method='DELETE'
)
```

**Request Without Authentication**
```python
# Public endpoint (no auth needed)
result = make_ps_api_request(
    endpoint='/api/public-data',
    use_auth=False
)
```

---

## Data Manipulation Functions

### `safe_get()`

Safely access nested dictionary values without raising KeyError.

#### Signature
```python
def safe_get(dictionary: Dict, *keys, default=None):
```

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `dictionary` | Dict | The dictionary to search |
| `*keys` | str | Variable number of keys to traverse (in order) |
| `default` | Any | Value to return if path doesn't exist (default: None) |

#### Returns

- The value at the specified key path
- `default` value if any key in the path doesn't exist

#### Examples

**Accessing Nested Values**
```python
data = {
    'season': {
        'name': '2024-25',
        'year': 2024,
        'teams': ['LAL', 'GSW', 'BOS']
    }
}

# Get nested value
season_name = safe_get(data, 'season', 'name')
print(season_name)  # Output: '2024-25'

# Get deeply nested value
first_team = safe_get(data, 'season', 'teams', 0)
print(first_team)  # Output: 'LAL'
```

**Handling Missing Keys**
```python
# Missing key returns default (None)
missing = safe_get(data, 'season', 'coach')
print(missing)  # Output: None

# Custom default value
missing_with_default = safe_get(data, 'season', 'coach', default='N/A')
print(missing_with_default)  # Output: 'N/A'

# Missing intermediate key
not_found = safe_get(data, 'playoffs', 'standings', default='No data')
print(not_found)  # Output: 'No data'
```

**Comparing with Standard Approach**
```python
# Without safe_get (risky)
try:
    value = data['season']['coach']['name']  # KeyError if 'coach' doesn't exist
except KeyError:
    value = 'N/A'

# With safe_get (safer)
value = safe_get(data, 'season', 'coach', 'name', default='N/A')
```

---

### `format_date()`

Convert ISO 8601 date strings to readable formats.

#### Signature
```python
def format_date(iso_date_string: str, format_type: str = 'short') -> str:
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iso_date_string` | str | Required | ISO 8601 date (e.g., `'2024-10-22T00:00:00.000Z'`) |
| `format_type` | str | `'short'` | Format: 'short', 'long', or 'medium' |

#### Format Types

| Type | Output Example | Format |
|------|-----------------|--------|
| `'short'` | `2024-10-22` | YYYY-MM-DD |
| `'medium'` | `Oct 22, 2024` | Mmm DD, YYYY |
| `'long'` | `October 22, 2024` | Month DD, YYYY |

#### Returns

- Formatted date string
- Original string (first 10 chars) if parsing fails

#### Examples

```python
iso_date = '2024-10-22T00:00:00.000Z'

# Short format (default)
short = format_date(iso_date)
print(short)  # Output: '2024-10-22'

# Long format
long = format_date(iso_date, 'long')
print(long)  # Output: 'October 22, 2024'

# Medium format
medium = format_date(iso_date, 'medium')
print(medium)  # Output: 'Oct 22, 2024'

# Handling invalid dates
invalid = format_date('invalid-date')
print(invalid)  # Output: 'invali' (first 10 chars)
```

---

### `chunk_list()`

Split a list into smaller chunks of specified size.

#### Signature
```python
def chunk_list(data: List, chunk_size: int) -> List[List]:
```

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | List | List to split |
| `chunk_size` | int | Size of each chunk |

#### Returns

- List of lists (chunks)
- Last chunk may be smaller if list length isn't divisible by chunk_size

#### Examples

**Basic Chunking**
```python
numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9]

chunks = chunk_list(numbers, 3)
print(chunks)  # Output: [[1, 2, 3], [4, 5, 6], [7, 8, 9]]

# Uneven chunks
chunks = chunk_list(numbers, 4)
print(chunks)  # Output: [[1, 2, 3, 4], [5, 6, 7, 8], [9]]
```

**Batch Processing**
```python
# Process games in batches
all_games = list(range(1, 1001))  # 1000 games

# Split into batches of 50
batch_size = 50
batches = chunk_list(all_games, batch_size)

for i, batch in enumerate(batches):
    print(f"Processing batch {i+1} with {len(batch)} games")
    # process_batch(batch)
```

---

### `merge_dicts()`

Merge multiple dictionaries with later dictionaries taking precedence.

#### Signature
```python
def merge_dicts(*dicts: Dict) -> Dict:
```

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `*dicts` | Dict | Variable number of dictionaries to merge |

#### Returns

- Single merged dictionary

#### Examples

**Basic Merge**
```python
dict1 = {'name': 'Lakers', 'city': 'Los Angeles'}
dict2 = {'year_founded': 1947, 'championships': 17}
dict3 = {'city': 'LA', 'arena': 'Crypto.com Arena'}

result = merge_dicts(dict1, dict2, dict3)
print(result)
# Output: {
#     'name': 'Lakers',
#     'year_founded': 1947,
#     'championships': 17,
#     'city': 'LA',  # Overridden by dict3
#     'arena': 'Crypto.com Arena'
# }
```

**Building Configuration**
```python
# Base config
base_config = {
    'api_timeout': 30,
    'retries': 3,
    'debug': False
}

# Environment-specific overrides
prod_overrides = {
    'debug': False,
    'api_timeout': 60
}

# Custom user config
user_config = {
    'debug': True  # For debugging
}

final_config = merge_dicts(base_config, prod_overrides, user_config)
print(final_config['debug'])  # Output: True
```

---

## Utility Functions

### `print_json()`

Pretty-print JSON data with indentation.

#### Signature
```python
def print_json(data: Union[Dict, List], indent: int = 2):
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data` | Dict or List | Required | Data to print |
| `indent` | int | 2 | Number of spaces for indentation |

#### Examples

```python
data = {
    'team': 'Lakers',
    'players': ['LeBron James', 'Anthony Davis'],
    'stats': {
        'wins': 45,
        'losses': 37
    }
}

# Default formatting (2-space indent)
print_json(data)
# Output:
# {
#   "team": "Lakers",
#   "players": [
#     "LeBron James",
#     "Anthony Davis"
#   ],
#   "stats": {
#     "wins": 45,
#     "losses": 37
#   }
# }

# Custom indentation
print_json(data, indent=4)
```

---

### `APIError` Exception

Custom exception for API-related errors.

#### Usage

```python
from cron.server_v2.ps_backend.utils.common_utils import make_ps_api_request, APIError

try:
    result = make_ps_api_request('/api/invalid-endpoint')
except APIError as e:
    print(f"API error occurred: {e}")
    # Handle error appropriately
```

---

## Error Handling

`make_ps_api_request()` raises `APIError` for various failure scenarios:

| Error Type | Cause | Example |
|-----------|-------|---------|
| HTTP Error | 4xx or 5xx response | `APIError: API error (404): Resource not found` |
| Timeout | Request exceeds timeout | `APIError: Request timed out after 30 seconds` |
| Connection Error | Network connectivity issue | `APIError: Connection error: [error details]` |
| Invalid JSON | Response not valid JSON | `APIError: Invalid JSON response: [error]` |

#### Error Handling Pattern

```python
from cron.server_v2.ps_backend.utils.common_utils import make_ps_api_request, APIError

try:
    result = make_ps_api_request('/api/games', params={'year': 2024})
    games = safe_get(result, 'data', default=[])
    print(f"Found {len(games)} games")

except APIError as e:
    print(f"Failed to fetch games: {e}")
    # Implement retry logic, fallback, etc.

except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## Examples

### Example 1: Fetch and Process Season Data

```python
from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request, safe_get, print_json, APIError
)

try:
    # Fetch season data
    response = make_ps_api_request(
        '/api/seasons',
        params={'year': 2024}
    )

    # Safely extract data
    seasons = safe_get(response, 'data', default=[])

    if not seasons:
        print("No seasons found")
    else:
        print(f"Found {len(seasons)} seasons:")
        print_json(seasons)

except APIError as e:
    print(f"Error fetching seasons: {e}")
```

### Example 2: Batch Create Games

```python
from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request, chunk_list, APIError
)

games_data = [
    {'date': '2024-10-22', 'home_team': 'LAL', 'away_team': 'GSW'},
    {'date': '2024-10-22', 'home_team': 'BOS', 'away_team': 'MIA'},
    # ... 100 more games
]

# Process in batches of 10
for batch in chunk_list(games_data, 10):
    try:
        for game in batch:
            result = make_ps_api_request(
                '/api/games',
                method='POST',
                data=game
            )
            print(f"Created game: {safe_get(result, 'id')}")
    except APIError as e:
        print(f"Batch failed: {e}")
        # Could implement retry logic here
```

### Example 3: Merge and Format Game Stats

```python
from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request, merge_dicts, format_date, safe_get
)

# Fetch multiple data sources
basic_stats = make_ps_api_request('/api/games/123')
advanced_stats = make_ps_api_request('/api/games/123/advanced-stats')
player_stats = make_ps_api_request('/api/games/123/player-stats')

# Merge all data
complete_game = merge_dicts(basic_stats, advanced_stats, player_stats)

# Extract and format information
game_date = format_date(safe_get(complete_game, 'date'), 'long')
home_team = safe_get(complete_game, 'home_team', default='Unknown')
score = safe_get(complete_game, 'final_score', default='TBA')

print(f"{game_date}: {home_team} - Final Score: {score}")
```

---

## Best Practices

### 1. **Always Use safe_get() for API Responses**
```python
# ✓ Good
value = safe_get(response, 'data', 'teams', 0, 'name', default='N/A')

# ✗ Bad
value = response['data']['teams'][0]['name']  # KeyError risk
```

### 2. **Handle APIError Exceptions**
```python
# ✓ Good
try:
    result = make_ps_api_request(endpoint)
except APIError as e:
    logger.error(f"API request failed: {e}")
    # Handle gracefully

# ✗ Bad - no error handling
result = make_ps_api_request(endpoint)
```

### 3. **Use Appropriate Timeout Values**
```python
# ✓ Good - for long-running operations
result = make_ps_api_request(
    endpoint,
    timeout=60  # 1 minute for bulk operations
)

# For quick operations
result = make_ps_api_request(
    endpoint,
    timeout=10  # 10 seconds for regular requests
)
```

### 4. **Batch Process Large Lists**
```python
# ✓ Good - process in manageable chunks
for chunk in chunk_list(large_list, 50):
    process_chunk(chunk)

# ✗ Bad - memory intensive
for item in large_list:  # If list has 100k+ items
    process_item(item)
```

### 5. **Log API Requests for Debugging**
```python
import logging

logger = logging.getLogger(__name__)

try:
    logger.debug(f"Making API request to {endpoint}")
    result = make_ps_api_request(endpoint, data=payload)
    logger.debug(f"API request successful: {result}")
except APIError as e:
    logger.error(f"API request failed: {e}")
```

### 6. **Use print_json() for Debugging**

```python
from cron.server_v2.ps_backend.utils.common_utils import print_json

# For development/debugging
print_json(response)

# Use proper logging in production
logger.debug(json.dumps(response, indent=2))
```

---

## Troubleshooting

### Issue: `APIError: Connection error`
**Cause**: Backend API is unreachable
**Solution**: 
- Verify `BACKEND_URL` in `.env` is correct
- Check network connectivity
- Ensure backend service is running

### Issue: `APIError: API error (401): Unauthorized`
**Cause**: Invalid or missing authentication token
**Solution**:
- Verify `TOKEN` in `.env` is correct
- Ensure token hasn't expired
- Check token has required permissions

### Issue: `APIError: Request timed out`
**Cause**: API taking too long to respond
**Solution**:
- Increase `timeout` parameter
- Check API server performance
- Consider batch processing

### Issue: `APIError: Invalid JSON response`
**Cause**: API returned non-JSON response
**Solution**:
- Verify endpoint URL is correct
- Check response content type
- Review API documentation

---

## Quick Reference

```python
# API Request
make_ps_api_request(endpoint, method='GET', params=None, data=None, use_auth=True, timeout=30)

# Safe Dictionary Access
safe_get(dict, key1, key2, key3, default=None)

# Date Formatting
format_date(iso_date_string, format_type='short')  # 'short', 'long', 'medium'

# List Chunking
chunk_list(list, chunk_size)

# Dictionary Merging
merge_dicts(dict1, dict2, dict3)

# Pretty Print
print_json(data, indent=2)

# Exception Handling
except APIError as e:
    # Handle API errors
```

---

*Last Updated: February 2026*

