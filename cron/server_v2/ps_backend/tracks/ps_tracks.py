"""
PS Tracks Module

Fetches all tracks from the Purple Sector API and returns a
dictionary of { location: id }.

Endpoint:
    GET /api/tracks/  - List all tracks with Track Intelligence data
"""

from typing import Dict, Any

from loguru import logger

from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request,
    safe_get,
    print_json,
    APIError
)


def fetch_tracks_location_id_map(page_size: int = 100) -> Dict[str, int]:
    """
    Fetch all tracks and return a dictionary mapping location -> track id.

    Calls GET /api/tracks/ with automatic pagination.

    Args:
        page_size (int): Number of tracks per page (max 100). Defaults to 100.

    Returns:
        Dict[str, int]: { location: id }
            Example: {'Sakhir': 1, 'Monza': 5, 'Monte Carlo': 8, ...}
            Tracks with a null/missing location are skipped.

    Raises:
        APIError: If the API request fails.

    Example:
        >>> location_map = fetch_tracks_location_id_map()
        >>> print(location_map['Sakhir'])
        1
    """
    try:
        logger.info("Fetching all tracks from API...")

        location_id_map: Dict[str, int] = {}
        page = 1

        while True:
            params: Dict[str, Any] = {
                'page': page,
                'pageSize': page_size,
            }

            logger.debug(f"Fetching tracks page {page}...")

            response = make_ps_api_request(
                endpoint='/api/tracks/',
                method='GET',
                params=params,
                timeout=30
            )

            tracks_list = safe_get(response, 'data', default=[])
            meta = safe_get(response, 'meta', default={})

            if not tracks_list:
                if page == 1:
                    logger.warning("No tracks found in API response")
                break

            for track in tracks_list:
                location = safe_get(track, 'location')
                track_id = safe_get(track, 'id')
                if location and track_id is not None:
                    location_id_map[location] = track_id
                    logger.debug(f"Mapped location='{location}' -> id={track_id}")
                else:
                    logger.warning(
                        f"Skipping track '{safe_get(track, 'name')}' — "
                        f"missing location or id (location={location!r}, id={track_id!r})"
                    )

            logger.debug(f"Page {page}: processed {len(tracks_list)} tracks")

            total_pages = safe_get(meta, 'totalPages', default=1)
            if page >= total_pages:
                break

            page += 1

        logger.info(f"Successfully built location->id map with {len(location_id_map)} entries")
        return location_id_map

    except APIError as e:
        logger.error(f"API Error while fetching tracks: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while fetching tracks: {e}")
        raise


# Example usage and testing
if __name__ == "__main__":

    logger.info("=" * 50)
    logger.info("PS Tracks — Location -> ID Map")
    logger.info("=" * 50)

    try:
        location_map = fetch_tracks_location_id_map()

        logger.info(f"\nTotal entries: {len(location_map)}")
        logger.info("\nSample entries:")
        for location, track_id in list(location_map.items()):
            logger.info(f"  '{location}' -> {track_id}")

        logger.info("\nFull map as JSON:")
        print_json(location_map)

        logger.success("Done!")

    except APIError as e:
        logger.error(f"API Error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")

