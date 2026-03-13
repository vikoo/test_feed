import json
import os
import re
from loguru import logger
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup, Tag


URL = "https://www.formula1.com/en/timing/f1-live-lite"
TABLE_CLASS = "w-full grid"

# Directory where this script lives — all output files go here
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS = ["Pos", "First Name", "Last Name", "Team", "Abbreviation", "Gap", "Tyre", "Tyres Used"]


def _parse_driver_cell(td: Tag) -> tuple[str, str, str, str]:
    """Return (first_name, last_name, team, abbreviation) from the driver <td>."""
    # First name: inside .font-normal hidden
    fn_span = td.find("span", class_=lambda c: c and "font-normal" in c)
    first_name = fn_span.get_text(strip=True) if fn_span else ""

    # Last name: inside .uppercase span
    ln_span = td.find("span", class_=lambda c: c and "uppercase" in c)
    last_name = ln_span.get_text(strip=True) if ln_span else ""

    # Team: desktop-only span with text-grey
    team_span = td.find("span", class_=lambda c: c and "text-grey-60" in c)
    team = team_span.get_text(strip=True) if team_span else ""

    # Abbreviation: tablet:hidden span (3-letter code)
    abbr_span = td.find("span", class_=lambda c: c and "tablet:hidden" in c)
    abbreviation = abbr_span.get_text(strip=True) if abbr_span else ""

    return first_name, last_name, team, abbreviation


def _parse_tyre_cell(td: Tag) -> str:
    """Extract tyre compound name from the <img> src inside the tyre <td>."""
    img = td.find("img")
    if img and img.get("src"):
        # src looks like: .../_next/static/media/soft.902bf68d.png
        match = re.search(r"/([a-z]+)\.[a-f0-9]+\.png", img["src"])
        if match:
            return match.group(1).capitalize()
    return ""


def _parse_table(soup: BeautifulSoup) -> list[dict]:
    """Find the timing table and return a list of dicts, one per driver row."""
    table = soup.find("table", class_=lambda c: c and all(cls in c.split() for cls in TABLE_CLASS.split()))

    if table is None:
        logger.error("Could not find the target table on the page.")
        all_tables = soup.find_all("table")
        logger.info(f"Total <table> tags on page: {len(all_tables)}")
        for i, t in enumerate(all_tables):
            logger.info(f"  table[{i}] classes: {t.get('class', [])}")
        return []

    # ── tbody rows ─────────────────────────────────────────────────────────────
    tbody = table.find("tbody")
    records: list[dict] = []

    if tbody:
        tds_list = [tr.find_all(["td", "th"]) for tr in tbody.find_all("tr")]
        for tds in tds_list:
            if len(tds) < 5:
                continue
            pos        = tds[0].get_text(strip=True)
            fn, ln, team, abbr = _parse_driver_cell(tds[1])
            gap        = tds[2].get_text(strip=True)
            tyre       = _parse_tyre_cell(tds[3])
            tyres_used = tds[4].get_text(strip=True)
            records.append(dict(zip(HEADERS, [pos, fn, ln, team, abbr, gap, tyre, tyres_used])))
        logger.info(f"Extracted {len(records)} data row(s).")
    else:
        logger.warning("No <tbody> found in the table.")

    return records


def scrape_f1_live_table() -> str:
    """
    Scrape the live timing table from the F1 website.
    Returns a JSON string — an array of objects, each mapping header names to values.
    """
    logger.info(f"Launching headless browser to scrape: {URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )

        logger.info("Navigating to page...")
        page.goto(URL, wait_until="networkidle", timeout=60_000)

        try:
            page.wait_for_selector(f'table.{TABLE_CLASS.replace(" ", ".")}', timeout=30_000)
            logger.info("Table found in DOM.")
        except Exception:
            logger.warning("Table selector timed out – attempting to parse whatever is rendered.")

        html = page.content()
        browser.close()

    # Save raw HTML snapshot
    html_path = os.path.join(SCRIPT_DIR, "f1_live_page_snapshot.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Raw HTML snapshot saved to {html_path}")

    soup = BeautifulSoup(html, "html.parser")
    return json.dumps(_parse_table(soup), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    json_str = scrape_f1_live_table()
    records = json.loads(json_str)

    print("\n=== F1 Live Timing Data ===")
    print(f"Total entries: {len(records)}")
    for entry in records:
        print(json.dumps(entry, ensure_ascii=False))

    # ── Save JSON ──────────────────────────────────────────────────────────────
    json_path = os.path.join(SCRIPT_DIR, "f1_live_data_output.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    logger.info(f"JSON saved → {json_path}")
