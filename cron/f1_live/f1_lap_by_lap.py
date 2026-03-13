import json
import os
import urllib.request
from bs4 import BeautifulSoup
from loguru import logger

API_URL = "https://cdn.monterosa.cloud/events/c0/c0243db7-347f-4d23-8a13-cf6401cea55b/history.json"

# Directory where this script lives — all output files go here
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _strip_html(html: str) -> list[str]:
    """Parse an HTML string and return a list of non-empty paragraph strings."""
    soup = BeautifulSoup(html, "html.parser")
    return [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]


def _parse_article_element(item: dict) -> dict:
    """
    Parse a content_type=article-element item into a clean dict.

    Fields:
      id             — item UUID
      content_type   — always "article-element"
      published_at   — ISO 8601 timestamp
      updated_at     — ISO 8601 timestamp
      title          — headline text
      subtitle       — time label / subtitle (e.g. "12:08")
      icon           — team name or special token (e.g. "Ferrari", "NA", "ChequeredFlag")
      image_url      — cloudinary/CDN image path (if present)
      body           — list of paragraph strings, stripped of HTML tags
      pin            — bool, whether the item is pinned
    """
    fields = item.get("custom_fields", {}).get("all", {})
    return {
        "id": item.get("id", ""),
        "content_type": item.get("content_type", ""),
        "published_at": item.get("published_at_iso", ""),
        "updated_at": item.get("updated_at_iso", ""),
        "title": fields.get("title", "").strip(),
        "subtitle": fields.get("subtitle", "").strip(),
        "icon": fields.get("icon", "").strip(),
        "image_url": fields.get("imageUrl", "").strip(),
        "body": _strip_html(fields.get("text", "")),
        "pin": fields.get("pin", False),
    }


def _parse_social_element(item: dict) -> dict:
    """
    Parse a content_type=social-element item into a clean dict.

    Fields:
      id             — item UUID
      content_type   — always "social-element"
      published_at   — ISO 8601 timestamp
      updated_at     — ISO 8601 timestamp
      platform       — e.g. "twitter"
      url            — link to the social post
      hide_media     — bool
      pin            — bool
    """
    fields = item.get("custom_fields", {}).get("all", {})
    return {
        "id": item.get("id", ""),
        "content_type": item.get("content_type", ""),
        "published_at": item.get("published_at_iso", ""),
        "updated_at": item.get("updated_at_iso", ""),
        "platform": fields.get("socialPlatform", "").strip(),
        "url": fields.get("url", "").strip(),
        "hide_media": fields.get("hideMedia", False),
        "pin": fields.get("pin", False),
    }


def _parse_external_article_element(item: dict) -> dict:
    """Parse a content_type=external-article-element (linked article card)."""
    fields = item.get("custom_fields", {}).get("all", {})
    return {
        "id": item.get("id", ""),
        "content_type": item.get("content_type", ""),
        "published_at": item.get("published_at_iso", ""),
        "updated_at": item.get("updated_at_iso", ""),
        "title": fields.get("title", "").strip(),
        "url": fields.get("url", "").strip(),
        "image_url": fields.get("imageUrl", "").strip(),
        "pin": fields.get("pin", False),
    }


def _parse_race_control_message(item: dict) -> dict:
    """Parse a content_type=race-control-message-element."""
    fields = item.get("custom_fields", {}).get("all", {})
    return {
        "id": item.get("id", ""),
        "content_type": item.get("content_type", ""),
        "published_at": item.get("published_at_iso", ""),
        "updated_at": item.get("updated_at_iso", ""),
        "message": fields.get("message", "").strip(),
        "flag": fields.get("flag", "").strip(),
        "category": fields.get("category", "").strip(),
        "pin": fields.get("pin", False),
    }


def _parse_commentary_element(item: dict) -> dict:
    """Parse a content_type=commentary-element (short live commentary line)."""
    fields = item.get("custom_fields", {}).get("all", {})
    return {
        "id": item.get("id", ""),
        "content_type": item.get("content_type", ""),
        "published_at": item.get("published_at_iso", ""),
        "updated_at": item.get("updated_at_iso", ""),
        "text": _strip_html(fields.get("text", "")),
        "subtitle": fields.get("subtitle", "").strip(),
        "pin": fields.get("pin", False),
    }


def fetch_lap_by_lap() -> str:
    """
    Fetch the lap-by-lap feed from the Monterosa CDN API.
    Returns a JSON string — an array of parsed feed objects.
    """
    logger.info(f"Fetching feed from: {API_URL}")
    with urllib.request.urlopen(API_URL, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    # Root may be a bare array or {"timeline": [...], "config": {...}, "version": N}
    if isinstance(data, list):
        items = data
    else:
        items = data.get("timeline") or data.get("items") or data.get("elements") or []
    logger.info(f"Total items received: {len(items)}")

    records = []
    skipped = 0
    for item in items:
        content_type = item.get("content_type")
        if content_type == "article-element":
            records.append(_parse_article_element(item))
        elif content_type == "social-element":
            records.append(_parse_social_element(item))
        elif content_type == "external-article-element":
            records.append(_parse_external_article_element(item))
        elif content_type == "race-control-message-element":
            records.append(_parse_race_control_message(item))
        elif content_type == "commentary-element":
            records.append(_parse_commentary_element(item))
        else:
            logger.warning(f"Unknown content_type '{content_type}' for item {item.get('id')} — skipping.")
            skipped += 1

    logger.info(f"Parsed {len(records)} item(s), skipped {skipped}.")
    return json.dumps(records, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    json_str = fetch_lap_by_lap()
    records = json.loads(json_str)

    print(f"\n=== F1 Lap-by-Lap Feed ({len(records)} entries) ===\n")
    for entry in records:
        print(json.dumps(entry, ensure_ascii=False))

    # ── Save JSON ──────────────────────────────────────────────────────────────
    json_path = os.path.join(SCRIPT_DIR, "f1_lap_by_lap_output.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    logger.info(f"JSON saved → {json_path}")

