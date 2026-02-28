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
from loguru import logger

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


def load_json_file(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Load and parse a JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data as dictionary, or None if error

    Example:
        >>> data = load_json_file('data.json')
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        log_error(f"File not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        log_error(f"Invalid JSON in {file_path}: {e}")
        return None
    except Exception as e:
        log_error(f"Error loading {file_path}: {e}")
        return None


def make_api_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30
) -> Optional[Dict[str, Any]]:
    """
    Make an HTTP API request with error handling.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        url: Full URL to request
        headers: Request headers
        json_data: JSON data for request body
        timeout: Request timeout in seconds

    Returns:
        Response JSON data, or None if error

    Example:
        >>> response = make_api_request('POST', 'https://api.example.com/data',
        ...                             headers={'Authorization': 'Bearer token'},
        ...                             json_data={'key': 'value'})
    """
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_data,
            timeout=timeout
        )
        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return {"success": True}

        return response.json()

    except requests.exceptions.HTTPError as e:
        try:
            error_data = response.json()
            log_error(f"HTTP {response.status_code}: {error_data}")
            return error_data
        except:
            log_error(f"HTTP error: {e}")
            return None
    except requests.exceptions.Timeout:
        log_error(f"Request timed out after {timeout} seconds")
        return None
    except requests.exceptions.ConnectionError as e:
        log_error(f"Connection error: {e}")
        return None
    except Exception as e:
        log_error(f"Request error: {e}")
        return None


def log_info(message: str):
    """Log an info message."""
    logger.info(message)


def log_success(message: str):
    """Log a success message."""
    logger.success(message)


def log_error(message: str):
    """Log an error message."""
    logger.error(message)


def log_warning(message: str):
    """Log a warning message."""
    logger.warning(message)



# Example usage
if __name__ == "__main__":
    logger.info("=== Common Utils Test ===\n")

    try:
        # Test API request
        logger.info("1. Testing API request...")
        result = make_ps_api_request('/api/season-types', params={'year': 2024})
        logger.info(f"   Success! Found {len(result.get('data', []))} items")

        # Test safe_get
        logger.info("2. Testing safe_get...")
        test_data = {'season': {'name': '2024-25', 'year': 2024}}
        name = safe_get(test_data, 'season', 'name')
        missing = safe_get(test_data, 'missing', 'key', default='N/A')
        logger.info(f"   Season name: {name}")
        logger.info(f"   Missing key: {missing}")

        # Test format_date
        logger.info("3. Testing format_date...")
        iso_date = '2024-10-22T00:00:00.000Z'
        short = format_date(iso_date, 'short')
        long = format_date(iso_date, 'long')
        logger.info(f"   Short format: {short}")
        logger.info(f"   Long format: {long}")

        # Test chunk_list
        logger.info("4. Testing chunk_list...")
        chunks = chunk_list([1, 2, 3, 4, 5, 6, 7], 3)
        logger.info(f"   Chunks: {chunks}")

        logger.success("All tests passed!")

    except APIError as e:
        logger.error(f"API Error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
