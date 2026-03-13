"""
lap_by_lap_with_html.py
~~~~~~~~~~~~~~~~~~~~~~~
Scrape the F1 Lap-by-Lap timeline feed from:
  https://www.formula1.com/en/timing/f1-live-lite#lap-by-lap

The lap-by-lap content lives inside a Monterosa iframe. This script:
  1. Opens the page with a headless Playwright browser.
  2. Navigates into the iframe served by interactioncloud.formula1.com.
  3. Waits for the timeline wrapper div
       class="timeline__Wrapper-bmHzUs cQjLWE"
     to appear and scrapes every feed card inside it.
  4. Falls back to the Monterosa CDN JSON API (same source used by
     f1_lap_by_lap.py) if the iframe approach fails.

Output
------
  - Prints a summary to stdout.
  - Saves f1_lap_by_lap_html_output.json next to this file.
  - Saves f1_lap_by_lap_iframe_snapshot.html (raw iframe HTML) for debugging.
"""

import json
import os
import re
import urllib.request

from bs4 import BeautifulSoup, Tag
from loguru import logger
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── Config ─────────────────────────────────────────────────────────────────
URL = "https://www.formula1.com/en/timing/f1-live-lite#lap-by-lap"
TIMELINE_WRAPPER_CLASS = "timeline__Wrapper-bmHzUs"   # partial – enough to find it
FALLBACK_API_URL = (
    "https://cdn.monterosa.cloud/events/c0/"
    "c0243db7-347f-4d23-8a13-cf6401cea55b/history.json"
)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── HTML parsing helpers ────────────────────────────────────────────────────

def _text(tag: Tag | None, strip: bool = True) -> str:
    """Safe getText from a BeautifulSoup tag."""
    if tag is None:
        return ""
    return tag.get_text(strip=strip) if strip else tag.get_text()


def _parse_card(card: Tag) -> dict:
    """
    Extract fields from a single timeline card element.

    The Monterosa widget renders cards with varying structures depending on
    content type (article, social embed, race-control message, etc.).
    We harvest whatever is available and return a flat dict.
    """
    result: dict = {}

    # ── timestamp / subtitle ──────────────────────────────────────────────
    time_tag = card.find(class_=re.compile(r"time|subtitle|timestamp", re.I))
    result["time"] = _text(time_tag)

    # ── title / headline ──────────────────────────────────────────────────
    headline = card.find(["h1", "h2", "h3", "h4"])
    if not headline:
        headline = card.find(class_=re.compile(r"title|headline", re.I))
    result["title"] = _text(headline)

    # ── body paragraphs ───────────────────────────────────────────────────
    paras = [p.get_text(strip=True) for p in card.find_all("p") if p.get_text(strip=True)]
    result["body"] = paras

    # ── icon / team label ─────────────────────────────────────────────────
    icon_tag = card.find(class_=re.compile(r"icon|team|badge", re.I))
    result["icon"] = _text(icon_tag)

    # ── image URL ─────────────────────────────────────────────────────────
    img = card.find("img")
    result["image_url"] = img.get("src", "") if img else ""

    # ── social embed URL ──────────────────────────────────────────────────
    link = card.find("a", href=re.compile(r"https?://", re.I))
    result["url"] = link["href"] if link else ""

    # ── raw text fallback (for race-control or short commentary lines) ────
    all_text = card.get_text(separator=" ", strip=True)
    if not result["title"] and not result["body"]:
        result["raw_text"] = all_text[:300]  # trim very long strings
    else:
        result["raw_text"] = ""

    return result


def _parse_timeline(soup: BeautifulSoup) -> list[dict]:
    """Find the timeline wrapper and parse every card inside it."""
    wrapper = soup.find(class_=re.compile(TIMELINE_WRAPPER_CLASS))
    if wrapper is None:
        logger.warning(
            f"Timeline wrapper '{TIMELINE_WRAPPER_CLASS}' not found in HTML."
        )
        # Dump all class names for debugging
        all_divs = soup.find_all("div", class_=True)
        class_set = {cls for d in all_divs for cls in (d.get("class") or [])}
        logger.debug(f"Available classes (sample): {list(class_set)[:30]}")
        return []

    # Each direct child of the wrapper is typically one timeline card
    # but the depth can vary — try a few selectors
    cards: list[Tag] = wrapper.find_all(
        class_=re.compile(r"card|item|entry|post|article|element", re.I),
        recursive=True,
    )
    if not cards:
        # Fall back: use every immediate child div
        cards = wrapper.find_all("div", recursive=False)

    logger.info(f"Found {len(cards)} timeline card(s) in wrapper.")
    records = []
    for card in cards:
        parsed = _parse_card(card)
        # Skip completely empty records
        if any(parsed.values()):
            records.append(parsed)
    return records


# ── Iframe scraping via Playwright ─────────────────────────────────────────

def _scrape_via_playwright() -> list[dict]:
    """
    Launch a headless browser, navigate to the F1 live-lite page, locate the
    Monterosa iframe, and scrape the timeline wrapper inside it.
    """
    logger.info(f"Launching headless browser → {URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        logger.info("Navigating to page (networkidle)…")
        page.goto(URL, wait_until="networkidle", timeout=90_000)

        # ── Locate the Monterosa iframe ─────────────────────────────────
        iframe_element = None
        for frame_locator in page.frames:
            if "monterosa" in frame_locator.url or "interactioncloud" in frame_locator.url:
                iframe_element = frame_locator
                logger.info(f"Found Monterosa iframe: {frame_locator.url}")
                break

        html_source = ""
        records: list[dict] = []

        if iframe_element is not None:
            try:
                # Wait for the timeline wrapper to appear inside the iframe
                iframe_element.wait_for_selector(
                    f'div[class*="{TIMELINE_WRAPPER_CLASS}"]',
                    timeout=30_000,
                )
                logger.info("Timeline wrapper found inside iframe.")
            except PlaywrightTimeoutError:
                logger.warning(
                    "Timed out waiting for timeline wrapper inside iframe."
                )

            html_source = iframe_element.content()
        else:
            logger.warning(
                "Monterosa iframe not found – falling back to main page HTML."
            )
            html_source = page.content()

        browser.close()

    if html_source:
        # Save snapshot for debugging
        snapshot_path = os.path.join(SCRIPT_DIR, "f1_lap_by_lap_iframe_snapshot.html")
        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(html_source)
        logger.info(f"HTML snapshot saved → {snapshot_path}")

        soup = BeautifulSoup(html_source, "html.parser")
        records = _parse_timeline(soup)

    return records


# ── Fallback: Monterosa CDN JSON API ───────────────────────────────────────

def _scrape_via_api() -> list[dict]:
    """
    Fetch lap-by-lap data directly from the Monterosa CDN JSON API.
    Returns simplified dicts consistent with the HTML parse output.
    """
    logger.info(f"Fetching fallback API: {FALLBACK_API_URL}")
    with urllib.request.urlopen(FALLBACK_API_URL, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("timeline")
            or data.get("items")
            or data.get("elements")
            or []
        )
    logger.info(f"API returned {len(items)} item(s).")

    records = []
    for item in items:
        fields = item.get("custom_fields", {}).get("all", {})
        soup = BeautifulSoup(fields.get("text", ""), "html.parser")
        body = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]

        records.append({
            "id": item.get("id", ""),
            "content_type": item.get("content_type", ""),
            "time": fields.get("subtitle", "").strip(),
            "title": fields.get("title", "").strip(),
            "body": body,
            "icon": fields.get("icon", "").strip(),
            "image_url": fields.get("imageUrl", "").strip(),
            "url": fields.get("url", "").strip(),
            "pin": fields.get("pin", False),
            "raw_text": "",
        })

    return records


# ── Public entry-point ──────────────────────────────────────────────────────

def fetch_lap_by_lap_html() -> str:
    """
    Fetch the F1 lap-by-lap feed via the HTML/iframe approach.
    Falls back to the Monterosa CDN API when the page scrape yields nothing.

    Returns a JSON string (array of feed objects).
    """
    records = _scrape_via_playwright()

    if not records:
        logger.warning(
            "No records from HTML scrape – switching to Monterosa CDN API fallback."
        )
        records = _scrape_via_api()

    logger.info(f"Total records collected: {len(records)}")
    return json.dumps(records, indent=2, ensure_ascii=False)


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    json_str = fetch_lap_by_lap_html()
    records = json.loads(json_str)

    print(f"\n=== F1 Lap-by-Lap Feed (HTML scrape) – {len(records)} entries ===\n")
    for entry in records:
        print(json.dumps(entry, ensure_ascii=False))

    # ── Save JSON ──────────────────────────────────────────────────────────
    out_path = os.path.join(SCRIPT_DIR, "f1_lap_by_lap_html_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    logger.info(f"JSON saved → {out_path}")

