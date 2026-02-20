"""
Common utilities for NBA Data Uploader.

This module provides shared utility functions that can be used across
different modules in the NBA Data Uploader project.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import requests

from cron.server_v2.ps_backend.utils.config import BACKEND_URL, TOKEN

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))


class APIError(Exception):
    """Custom exception for API errors"""
    pass


def make_ps_api_request(
    endpoint: str,
    method: str = 'GET',
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    use_auth: bool = True,
    timeout: int = 30
) -> Union[Dict[str, Any], List[Any]]:
    """
    Make a request to the PS backend API.

    This is a general-purpose utility for making API calls to the PS backend.
    It handles authentication, error handling, and JSON parsing.

    Args:
        endpoint: API endpoint path (e.g., '/api/season-types')
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        params: Query parameters dictionary
        data: Request body data (for POST/PUT requests)
        use_auth: Whether to include authentication token
        timeout: Request timeout in seconds

    Returns:
        JSON response as dictionary or list

    Raises:
        APIError: If the API request fails

    Example:
        >>> # GET request
        >>> result = make_ps_api_request('/api/season-types', params={'year': 2024})
        >>>
        >>> # POST request
        >>> new_data = make_ps_api_request(
        ...     '/api/games',
        ...     method='POST',
        ...     data={'game_id': 123, 'home_team': 'LAL'}
        ... )
    """
    url = f"{BACKEND_URL}{endpoint}"
    headers = {
        'Content-Type': 'application/json'
    }

    if use_auth and TOKEN:
        headers['Authorization'] = f'Bearer {TOKEN}'

    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data, params=params, timeout=timeout)
        elif method.upper() == 'PUT':
            response = requests.put(url, headers=headers, json=data, params=params, timeout=timeout)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers, params=params, timeout=timeout)
        elif method.upper() == 'PATCH':
            response = requests.patch(url, headers=headers, json=data, params=params, timeout=timeout)
        else:
            raise APIError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()

        # Handle empty responses
        if response.status_code == 204 or not response.content:
            return {}

        return response.json()

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error occurred: {e}"
        try:
            if 'response' in locals():
                error_detail = response.json()
                error_msg = f"API error ({response.status_code}): {error_detail.get('message', str(e))}"
        except:
            pass
        raise APIError(error_msg)
    except requests.exceptions.Timeout:
        raise APIError(f"Request timed out after {timeout} seconds")
    except requests.exceptions.ConnectionError as e:
        raise APIError(f"Connection error: {e}")
    except requests.exceptions.RequestException as e:
        raise APIError(f"Request failed: {e}")
    except ValueError as e:
        raise APIError(f"Invalid JSON response: {e}")


def safe_get(dictionary: Dict, *keys, default=None):
    """
    Safely get nested dictionary values.

    Args:
        dictionary: The dictionary to search
        *keys: Sequence of keys to traverse
        default: Default value if key path doesn't exist

    Returns:
        The value at the key path, or default if not found

    Example:
        >>> data = {'season': {'name': '2024-25', 'year': 2024}}
        >>> safe_get(data, 'season', 'name')
        '2024-25'
        >>> safe_get(data, 'season', 'missing', default='N/A')
        'N/A'
    """
    result = dictionary
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
            if result is None:
                return default
        else:
            return default
    return result


def format_date(iso_date_string: str, format_type: str = 'short') -> str:
    """
    Format an ISO 8601 date string to a more readable format.

    Args:
        iso_date_string: ISO 8601 date string (e.g., '2024-10-22T00:00:00.000Z')
        format_type: 'short' for YYYY-MM-DD, 'long' for full date

    Returns:
        Formatted date string

    Example:
        >>> format_date('2024-10-22T00:00:00.000Z')
        '2024-10-22'
        >>> format_date('2024-10-22T00:00:00.000Z', 'long')
        'October 22, 2024'
    """
    from datetime import datetime

    try:
        # Parse ISO date
        dt = datetime.fromisoformat(iso_date_string.replace('Z', '+00:00'))

        if format_type == 'short':
            return dt.strftime('%Y-%m-%d')
        elif format_type == 'long':
            return dt.strftime('%B %d, %Y')
        elif format_type == 'medium':
            return dt.strftime('%b %d, %Y')
        else:
            return dt.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        return iso_date_string[:10] if len(iso_date_string) >= 10 else iso_date_string


def print_json(data: Union[Dict, List], indent: int = 2):
    """
    Pretty print JSON data.

    Args:
        data: Dictionary or list to print
        indent: Number of spaces for indentation

    Example:
        >>> data = {'name': 'Lakers', 'city': 'Los Angeles'}
        >>> print_json(data)
    """
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def chunk_list(data: List, chunk_size: int) -> List[List]:
    """
    Split a list into chunks of specified size.

    Args:
        data: List to split
        chunk_size: Size of each chunk

    Returns:
        List of chunks

    Example:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def merge_dicts(*dicts: Dict) -> Dict:
    """
    Merge multiple dictionaries, with later dicts taking precedence.

    Args:
        *dicts: Variable number of dictionaries to merge

    Returns:
        Merged dictionary

    Example:
        >>> merge_dicts({'a': 1}, {'b': 2}, {'a': 3})
        {'a': 3, 'b': 2}
    """
    result = {}
    for d in dicts:
        result.update(d)
    return result


# Example usage
if __name__ == "__main__":
    print("=== Common Utils Test ===\n")

    try:
        # Test API request
        print("1. Testing API request...")
        result = make_ps_api_request('/api/season-types', params={'year': 2024})
        print(f"   ✓ Success! Found {len(result.get('data', []))} items\n")

        # Test safe_get
        print("2. Testing safe_get...")
        test_data = {'season': {'name': '2024-25', 'year': 2024}}
        name = safe_get(test_data, 'season', 'name')
        missing = safe_get(test_data, 'missing', 'key', default='N/A')
        print(f"   ✓ Season name: {name}")
        print(f"   ✓ Missing key: {missing}\n")

        # Test format_date
        print("3. Testing format_date...")
        iso_date = '2024-10-22T00:00:00.000Z'
        short = format_date(iso_date, 'short')
        long = format_date(iso_date, 'long')
        print(f"   ✓ Short format: {short}")
        print(f"   ✓ Long format: {long}\n")

        # Test chunk_list
        print("4. Testing chunk_list...")
        chunks = chunk_list([1, 2, 3, 4, 5, 6, 7], 3)
        print(f"   ✓ Chunks: {chunks}\n")

        print("✅ All tests passed!")

    except APIError as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
