"""
PS Seasons Module

This module handles fetching season data from the Purple Sector API and
provides utilities to work with season information.

Endpoints:
    GET /api/seasons/  - Fetch all seasons
"""

from typing import Dict, Optional

from loguru import logger

from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request,
    safe_get,
    print_json,
    APIError
)



def fetch_all_seasons() -> Dict[str, int]:
    """
    Fetch all seasons from the PS Backend API and return a dictionary
    mapping year to season ID.

    This function calls the `/api/seasons/` endpoint and processes the
    response to create a mapping of season year to season ID.

    Returns:
        Dict[str, int]: Dictionary with format {year: id}
                       Example: {'2023': 1, '2024': 2, '2025': 3}

    Raises:
        APIError: If the API request fails

    Example:
        >>> seasons = fetch_all_seasons()
        >>> print(seasons)
        {'2023': 1, '2024': 2, '2025': 3}
    """
    try:
        logger.info("Fetching all seasons from API...")

        # Make API request to fetch seasons
        response = make_ps_api_request(
            endpoint='/api/seasons/',
            method='GET',
            timeout=30
        )

        logger.debug(f"API Response: {response}")

        # Extract seasons data from response
        seasons_list = safe_get(response, 'data', default=[])

        if not seasons_list:
            logger.warning("No seasons found in API response")
            return {}

        logger.info(f"Found {len(seasons_list)} seasons")

        # Create dictionary mapping year to id
        seasons_dict = {}
        for season in seasons_list:
            # Extract year and id from season object
            year = safe_get(season, 'year')
            season_id = safe_get(season, 'id')

            if year is not None and season_id is not None:
                # Convert year to string for consistent dictionary key format
                year_str = str(year)
                seasons_dict[year_str] = season_id
                logger.debug(f"Mapped year {year_str} to season ID {season_id}")
            else:
                logger.warning(f"Skipping season with incomplete data: {season}")

        logger.info(f"Successfully created season mapping with {len(seasons_dict)} entries")
        return seasons_dict

    except APIError as e:
        logger.error(f"API Error while fetching seasons: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while fetching seasons: {e}")
        raise


def get_season_by_year(year: int, seasons_dict: Optional[Dict[str, int]] = None) -> Optional[int]:
    """
    Get the season ID for a specific year.

    This is a utility function to lookup a season ID from the seasons dictionary.

    Args:
        year (int): The season year to lookup
        seasons_dict (Dict[str, int]): The seasons dictionary. If None, fetches from API.

    Returns:
        Optional[int]: Season ID if found, None otherwise

    Example:
        >>> season_id = get_season_by_year(2024)
        >>> print(season_id)
        2
    """
    try:
        if seasons_dict is None:
            seasons_dict = fetch_all_seasons()

        year_str = str(year)
        season_id = seasons_dict.get(year_str)

        if season_id is None:
            logger.warning(f"Season not found for year {year}")
        else:
            logger.debug(f"Found season ID {season_id} for year {year}")

        return season_id

    except Exception as e:
        logger.error(f"Error looking up season for year {year}: {e}")
        return None


def display_seasons(seasons_dict: Dict[str, int]):
    """
    Display seasons dictionary in a formatted way.

    Args:
        seasons_dict (Dict[str, int]): Dictionary with format {year: id}

    Example:
        >>> seasons = fetch_all_seasons()
        >>> display_seasons(seasons)
    """
    if not seasons_dict:
        logger.warning("No seasons to display")
        return

    logger.info(f"\n{'Year':<10} {'Season ID':<15}")
    logger.info("-" * 25)

    for year in sorted(seasons_dict.keys()):
        season_id = seasons_dict[year]
        logger.info(f"{year:<10} {season_id:<15}")

    logger.info(f"\nTotal: {len(seasons_dict)} seasons\n")


# Example usage and testing
if __name__ == "__main__":

    logger.info("=" * 50)
    logger.info("PS Seasons Fetcher")
    logger.info("=" * 50)

    try:
        # Fetch all seasons
        logger.info("\n1. Fetching all seasons from API...")
        seasons = fetch_all_seasons()

        # Display results
        logger.info("\n2. Displaying fetched seasons:")
        display_seasons(seasons)

        # Print as JSON
        logger.info("3. Seasons as JSON:")
        print_json(seasons)

        # Lookup specific year
        logger.info("\n4. Looking up specific years:")
        test_years = [2023, 2024, 2025]
        for year in test_years:
            season_id = get_season_by_year(year, seasons)
            if season_id:
                logger.info(f"   Year {year} -> Season ID {season_id}")
            else:
                logger.warning(f"   Year {year} -> Not found")

        logger.success("All operations completed successfully!")

    except APIError as e:
        logger.error(f"API Error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")

