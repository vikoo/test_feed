"""
Banner Upload Script
This script uploads banner data to the Purple Sector API using the /api/banners/ endpoint
"""

import sys
import os
from typing import Dict, Any

# Add parent directory to path to import config and common_utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from cron.server_v2.ps_backend.utils.config import API_BASE_URL, API_ENDPOINTS, DEFAULT_HEADERS, TOKEN
from cron.server_v2.ps_backend.utils.common_utils import make_api_request, load_json_file, log_info, log_error, log_success


def transform_banner_data(banner: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform banner data from banners.json format to API request format

    Args:
        banner: Banner data from banners.json

    Returns:
        Transformed banner data for API request
    """
    # Build the base data
    transformed = {
        "type": banner.get("type", "IMAGE"),
        "title": banner.get("title", ""),
        "description": banner.get("description"),
        "ctaText": banner.get("ctaText"),
        "ctaUrl": banner.get("ctaUrl"),
        "order": banner.get("order", 0),
        "startDate": banner.get("startDate"),
        "endDate": banner.get("endDate"),
        "isActive": banner.get("isActive", False),
        "bannerColor": banner.get("bannerColor"),
        "ctaType": banner.get("ctaType")
    }

    # Handle image field - only include if it has a value
    # If null or empty, pass empty string (API accepts this)
    image_value = banner.get("image")
    if image_value is None or image_value == "":
        transformed["image"] = ""
    else:
        transformed["image"] = image_value

    return transformed


def upload_banner(banner_data: Dict[str, Any]) -> bool:
    """
    Upload a single banner to the API

    Args:
        banner_data: Transformed banner data

    Returns:
        True if upload successful, False otherwise
    """
    endpoint = f"{API_BASE_URL}{API_ENDPOINTS['banners']}"

    # Prepare headers with token from config.py
    headers = DEFAULT_HEADERS.copy()
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    try:
        log_info(f"Uploading banner: {banner_data.get('title', 'Untitled')}")

        response = make_api_request(
            method="POST",
            url=endpoint,
            headers=headers,
            json_data=banner_data
        )

        if response and response.get("success"):
            log_success(f"Successfully uploaded banner: {banner_data.get('title')}")
            return True
        else:
            error_msg = response.get("error", {}).get("message") if response else "Unknown error"
            log_error(f"Failed to upload banner: {banner_data.get('title')} - {error_msg}")
            return False

    except Exception as e:
        log_error(f"Exception uploading banner {banner_data.get('title')}: {str(e)}")
        return False


def upload_all_banners(banners_file_path: str) -> Dict[str, int]:
    """
    Upload all banners from the banners.json file

    Args:
        banners_file_path: Path to banners.json file

    Returns:
        Dictionary with upload statistics
    """
    stats = {
        "total": 0,
        "successful": 0,
        "failed": 0
    }

    try:
        # Load banners data
        log_info(f"Loading banners from: {banners_file_path}")
        banners_data = load_json_file(banners_file_path)

        if not banners_data:
            log_error("Failed to load banners data")
            return stats

        # Extract banners from nested structure
        banner_entries = banners_data.get("data", {}).get("api::banner.banner", {})

        if not banner_entries:
            log_error("No banner entries found in data")
            return stats

        log_info(f"Found {len(banner_entries)} banners to upload")

        # Show authentication status
        if TOKEN:
            log_info(f"Using API token from config.py: {TOKEN[:20]}...")
        else:
            log_info("No API token configured (uploading without authentication)")

        # Upload each banner
        for banner_id, banner_data in banner_entries.items():
            stats["total"] += 1

            # Transform banner data to API format
            transformed_data = transform_banner_data(banner_data)

            # Upload banner
            success = upload_banner(transformed_data)

            if success:
                stats["successful"] += 1
            else:
                stats["failed"] += 1

        # Print summary
        log_info("\n" + "="*60)
        log_info("UPLOAD SUMMARY")
        log_info("="*60)
        log_info(f"Total banners: {stats['total']}")
        log_success(f"Successful uploads: {stats['successful']}")
        if stats['failed'] > 0:
            log_error(f"Failed uploads: {stats['failed']}")
        log_info("="*60 + "\n")

        return stats

    except Exception as e:
        log_error(f"Error in upload_all_banners: {str(e)}")
        return stats


def main():
    """
    Main function to run the banner upload script
    """
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    banners_file = os.path.join(script_dir, "banners.json")

    log_info("Starting Banner Upload Script")
    log_info(f"Target API: {API_BASE_URL}")
    log_info(f"Banners file: {banners_file}")

    # Check if file exists
    if not os.path.exists(banners_file):
        log_error(f"Banners file not found: {banners_file}")
        return

    # Upload all banners (token is automatically used from config.py)
    stats = upload_all_banners(banners_file)

    # Exit with appropriate code
    if stats["failed"] > 0:
        log_error("Some uploads failed")
        sys.exit(1)
    elif stats["successful"] > 0:
        log_success("All uploads completed successfully!")
        sys.exit(0)
    else:
        log_error("No banners were uploaded")
        sys.exit(1)


if __name__ == "__main__":
    main()

