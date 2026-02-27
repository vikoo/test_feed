import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import re
from typing import Optional


def parse_race_url(url):
    """
    Parse the Formula1.com race URL to extract year and race name.

    Args:
        url (str): URL like https://www.formula1.com/en/racing/2026/australia

    Returns:
        dict: Dictionary with 'year' and 'race_name' keys
    """
    match = re.search(r'/racing/(\d{4})/([^/]+)', url)
    if match:
        return {
            'year': match.group(1),
            'race_name': match.group(2).replace('-', ' ').title()
        }
    return {'year': None, 'race_name': None}


def parse_date_time(date_str: str, time_str: str, year: str) -> Optional[str]:
    """
    Parse date and time into a combined datetime string.
    Extracts only the start time from ranges.

    Args:
        date_str (str): Date in format "DDMon" (e.g., "06Mar")
        time_str (str): Time in format "HH:MM" or "HH:MM-HH:MM"
        year (str): Year as string

    Returns:
        str: Combined datetime in format "YYYY-MM-DD HH:MM" or None if parsing fails
    """
    try:
        # Extract start time only
        if '-' in time_str or '–' in time_str:
            separator = '-' if '-' in time_str else '–'
            start_time = time_str.split(separator)[0].strip()
        else:
            start_time = time_str.strip()

        # Parse the date
        date_obj = datetime.strptime(f"{date_str}{year}", "%d%b%Y")

        # Combine date and time
        datetime_str = f"{date_obj.strftime('%Y-%m-%d')} {start_time}"

        return datetime_str
    except Exception as e:
        print(f"Error parsing date/time: {e}")
        return None


def get_timezone_offset_for_race(race_name: str) -> int:
    """
    Get the UTC offset for a race location.

    Args:
        race_name (str): Name of the race location

    Returns:
        int: UTC offset in hours (positive or negative)
    """
    # Common F1 race locations and their UTC offsets
    # Note: These are approximate and may need adjustment for DST
    timezone_map = {
        'australia': 11,  # Melbourne - AEDT (UTC+11) during March
        'bahrain': 3,
        'saudi arabia': 3,
        'saudi-arabia': 3,
        'japan': 9,
        'china': 8,
        'miami': -4,  # EDT
        'monaco': 2,  # CEST
        'spain': 2,  # CEST
        'canada': -4,  # EDT
        'austria': 2,  # CEST
        'great britain': 1,  # BST
        'great-britain': 1,
        'hungary': 2,  # CEST
        'belgium': 2,  # CEST
        'netherlands': 2,  # CEST
        'italy': 2,  # CEST
        'azerbaijan': 4,
        'singapore': 8,
        'united states': -5,  # CDT (Austin)
        'united-states': -5,
        'mexico': -6,  # CST
        'brazil': -3,
        'las vegas': -8,  # PST
        'las-vegas': -8,
        'qatar': 3,
        'abu dhabi': 4,
        'abu-dhabi': 4,
    }

    race_key = race_name.lower().strip()
    return timezone_map.get(race_key, 0)  # Default to UTC if unknown


def convert_time_to_utc(local_time: str, date_str: str, year: str, race_name: str) -> Optional[str]:
    """
    Convert local race time to UTC (start time only).

    Args:
        local_time (str): Time in format "HH:MM" or "HH:MM-HH:MM"
        date_str (str): Date in format "DDMon" (e.g., "06Mar")
        year (str): Year as string
        race_name (str): Name of the race location for timezone detection

    Returns:
        str: UTC time in format "HH:MM", or None if conversion fails
    """
    try:
        # Get timezone offset
        offset_hours = get_timezone_offset_for_race(race_name)

        # Parse the date
        date_obj = datetime.strptime(f"{date_str}{year}", "%d%b%Y")

        # Extract start time only
        if '-' in local_time or '–' in local_time:
            separator = '-' if '-' in local_time else '–'
            start_time = local_time.split(separator)[0].strip()
        else:
            start_time = local_time.strip()

        # Convert to UTC
        time_dt = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} {start_time}", "%Y-%m-%d %H:%M")
        time_utc = time_dt - timedelta(hours=offset_hours)

        return time_utc.strftime('%H:%M')

    except Exception as e:
        print(f"Error converting time to UTC: {e}")
        return None


def convert_datetime_to_utc(local_datetime: str, race_name: str) -> Optional[str]:
    """
    Convert local race datetime to UTC datetime.

    Args:
        local_datetime (str): Datetime in format "YYYY-MM-DD HH:MM"
        race_name (str): Name of the race location for timezone detection

    Returns:
        str: UTC datetime in format "YYYY-MM-DD HH:MM", or None if conversion fails
    """
    try:
        # Get timezone offset
        offset_hours = get_timezone_offset_for_race(race_name)

        # Parse the datetime
        dt = datetime.strptime(local_datetime, "%Y-%m-%d %H:%M")

        # Convert to UTC
        dt_utc = dt - timedelta(hours=offset_hours)

        return dt_utc.strftime('%Y-%m-%d %H:%M')

    except Exception as e:
        print(f"Error converting datetime to UTC: {e}")
        return None


def extract_f1_schedule(url):
    """
    Extract F1 schedule from the given Formula1.com race page URL.

    Args:
        url (str): The URL of the F1 race page (e.g., https://www.formula1.com/en/racing/2026/australia)

    Returns:
        dict: A dictionary containing the extracted schedule information
    """
    try:
        # Set up headers to mimic a browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Fetch the page
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        # Parse the HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract race info from URL
        race_info = parse_race_url(url)
        year = race_info['year']
        race_name = race_info['race_name']

        schedule_data = {
            'url': url,
            'year': year,
            'race_name': race_name,
            'extracted_at': datetime.now().isoformat(),
            'sessions': []
        }

        # Look for the schedule UL - it has a grid layout with specific columns for schedule
        # The class contains 'grid' and 'gap-' which are typical for F1 schedule grids
        all_uls = soup.find_all('ul')

        schedule_ul = None
        for ul in all_uls:
            ul_class = ' '.join(ul.get('class', []))
            # Look for the grid layout that contains schedule information
            if 'grid' in ul_class and 'gap-x-px' in ul_class and 'grid-cols' in ul_class:
                # Check if it contains session-like content
                li_elements = ul.find_all('li')
                if li_elements and len(li_elements) <= 10:  # Reasonable number for race sessions
                    text = ul.get_text(strip=True)
                    # Check for schedule keywords
                    if any(keyword in text for keyword in ['Practice', 'Qualifying', 'Race', 'Sprint']):
                        schedule_ul = ul
                        break

        if not schedule_ul:
            print(f"Could not find schedule UL element")
            return schedule_data

        # Process each li element in the schedule
        li_elements = schedule_ul.find_all('li', recursive=False)

        for li in li_elements:
            session_info = extract_session_info(li, year=year, race_name=race_name)
            if session_info:
                schedule_data['sessions'].append(session_info)

        return schedule_data

    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return None
    except Exception as e:
        print(f"Error parsing schedule: {e}")
        return None


def extract_session_info(li_element, year=None, race_name=None):
    """
    Extract session information from a list item element.

    Args:
        li_element: BeautifulSoup element representing a list item
        year (str): Year for UTC conversion
        race_name (str): Race name for timezone detection

    Returns:
        dict: Dictionary containing session information
    """
    session_info = {}

    try:
        # Extract all text content
        text_content = li_element.get_text(strip=True, separator='|')

        # The F1 schedule grid typically has: Date | Icon | Session Name | Time(s)
        # Let's extract all child elements in order
        all_text_elements = []
        for child in li_element.descendants:
            if child.name in ['span', 'p', 'div', 'time'] and child.get_text(strip=True):
                text = child.get_text(strip=True)
                if text and text not in all_text_elements:
                    all_text_elements.append(text)

        # Look for session name (e.g., "Practice 1", "Qualifying", "Race")
        session_keywords = ['Practice', 'Qualifying', 'Race', 'Sprint']
        session_name = None
        for text in all_text_elements:
            if any(keyword in text for keyword in session_keywords):
                session_name = text
                break

        if session_name:
            session_info['session_name'] = session_name

        # Look for date information (typically day and month like "06Mar")
        date_pattern = None
        for text in all_text_elements:
            # Check if it looks like a date (e.g., "06Mar", "07Mar")
            if len(text) >= 4 and text[:2].isdigit() and text[2:].isalpha():
                date_pattern = text
                break

        # Look for time information
        # First check for time ranges (e.g., "01:30-02:30")
        # Then check for single times (e.g., "04:00")
        local_time = None
        for text in all_text_elements:
            # Check if it looks like a time range (contains : and -)
            if ':' in text and ('-' in text or '–' in text):
                local_time = text
                break
            # Check if it looks like a single time (HH:MM format)
            elif re.match(r'^\d{2}:\d{2}$', text):
                local_time = text
                break

        # Create combined datetime fields
        if local_time and date_pattern and year:
            # Parse and combine date + time (start time only)
            datetime_local = parse_date_time(date_pattern, local_time, year)
            if datetime_local:
                session_info['datetime_local'] = datetime_local

                # Convert to UTC
                if race_name:
                    datetime_utc = convert_datetime_to_utc(datetime_local, race_name)
                    if datetime_utc:
                        session_info['datetime_utc'] = datetime_utc

        # Extract datetime attribute if available
        datetime_elem = li_element.find('time')
        if datetime_elem and datetime_elem.get('datetime'):
            session_info['datetime_iso'] = datetime_elem.get('datetime')

        # Store all classes for reference
        if li_element.get('class'):
            session_info['classes'] = ' '.join(li_element.get('class'))

        # Store raw text as fallback
        session_info['raw_text'] = text_content

        # Get all data attributes
        data_attrs = {k: v for k, v in li_element.attrs.items() if k.startswith('data-')}
        if data_attrs:
            session_info['data_attributes'] = data_attrs

        return session_info if session_info else None

    except Exception as e:
        print(f"Error extracting session info: {e}")
        return None


def extract_f1_schedule_detailed(url):
    """
    Extract F1 schedule with more detailed parsing.
    This function provides a more comprehensive extraction.

    Args:
        url (str): The URL of the F1 race page

    Returns:
        dict: Detailed schedule information
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the div with the specified class
        schedule_container = soup.find('div', class_='Container-module_inner__UkLYJ')

        if not schedule_container:
            print(f"Could not find schedule container")
            # Try to find any ul li structure as fallback
            all_lis = soup.find_all('li')
            print(f"Found {len(all_lis)} li elements in the page")
            return {
                'url': url,
                'error': 'Container not found',
                'total_li_elements': len(all_lis)
            }

        # Get all the raw HTML for debugging
        schedule_data = {
            'url': url,
            'extracted_at': datetime.now().isoformat(),
            'container_found': True,
            'schedule_items': []
        }

        # Find all li elements
        all_li = schedule_container.find_all('li')

        for idx, li in enumerate(all_li):
            item = {
                'index': idx,
                'html': str(li),
                'text': li.get_text(strip=True, separator=' | '),
                'classes': li.get('class', []),
                'attributes': dict(li.attrs)
            }

            # Try to extract structured data
            structured = {}

            # Look for headings
            headings = li.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if headings:
                structured['headings'] = [h.get_text(strip=True) for h in headings]

            # Look for time elements
            times = li.find_all('time')
            if times:
                structured['times'] = [{
                    'text': t.get_text(strip=True),
                    'datetime': t.get('datetime')
                } for t in times]

            # Look for spans
            spans = li.find_all('span')
            if spans:
                structured['spans'] = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]

            # Look for links
            links = li.find_all('a')
            if links:
                structured['links'] = [{
                    'text': a.get_text(strip=True),
                    'href': a.get('href')
                } for a in links]

            if structured:
                item['structured'] = structured

            schedule_data['schedule_items'].append(item)

        return schedule_data

    except Exception as e:
        print(f"Error in detailed extraction: {e}")
        return {
            'url': url,
            'error': str(e)
        }


def print_schedule(schedule_data):
    """
    Print the extracted schedule in a readable format.

    Args:
        schedule_data (dict): The schedule data returned by extract_f1_schedule
    """
    if not schedule_data:
        print("No schedule data available")
        return

    print(f"\nF1 Schedule extracted from: {schedule_data.get('url')}")
    print(f"Race: {schedule_data.get('race_name')} {schedule_data.get('year')}")
    print(f"Extracted at: {schedule_data.get('extracted_at')}")
    print("=" * 80)

    if 'sessions' in schedule_data:
        print(f"\n{'Session':<20} {'DateTime Local':<20} {'DateTime UTC':<20}")
        print("-" * 65)
        for session in schedule_data['sessions']:
            session_name = session.get('session_name', 'Unknown')
            dt_local = session.get('datetime_local', 'TBD')
            dt_utc = session.get('datetime_utc', 'TBD')
            print(f"{session_name:<20} {dt_local:<20} {dt_utc:<20}")
    elif 'schedule_items' in schedule_data:
        for item in schedule_data['schedule_items']:
            print(f"\nItem {item['index']}:")
            print(f"  Text: {item['text']}")
            if 'structured' in item:
                for key, value in item['structured'].items():
                    print(f"  {key}: {value}")

    print("\n" + "=" * 80)


def save_schedule_to_json(schedule_data, output_file='f1_schedule.json'):
    """
    Save the extracted schedule to a JSON file.

    Args:
        schedule_data (dict): The schedule data to save
        output_file (str): The output file path
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(schedule_data, f, indent=2, ensure_ascii=False)
        print(f"Schedule saved to {output_file}")
    except Exception as e:
        print(f"Error saving to JSON: {e}")


def debug_page_structure(url):
    """
    Debug function to inspect the page structure and find schedule elements.

    Args:
        url (str): The URL to inspect
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        print("\n=== DEBUG: Page Structure Analysis ===")

        # Check for the specific container
        schedule_container = soup.find('div', class_='Container-module_inner__UkLYJ')
        if schedule_container:
            print(f"✓ Found Container-module_inner__UkLYJ")
            print(f"  Container HTML length: {len(str(schedule_container))} characters")

            # Check for ul elements
            ul_elements = schedule_container.find_all('ul')
            print(f"  Found {len(ul_elements)} <ul> elements")

            for idx, ul in enumerate(ul_elements):
                li_elements = ul.find_all('li')
                print(f"    UL {idx}: {len(li_elements)} <li> elements")

                if li_elements:
                    # Show first li as example
                    first_li = li_elements[0]
                    print(f"      First <li> text: {first_li.get_text(strip=True)[:100]}")
                    print(f"      First <li> classes: {first_li.get('class')}")
        else:
            print(f"✗ Container-module_inner__UkLYJ NOT found")

            # Search for other potential containers
            print("\n  Searching for alternative containers...")
            all_divs = soup.find_all('div', class_=lambda x: x and 'container' in ' '.join(x).lower())
            print(f"  Found {len(all_divs)} divs with 'container' in class name")

            for div in all_divs[:5]:  # Show first 5
                classes = ' '.join(div.get('class', []))
                print(f"    - {classes}")

        # Check for all ul/li structures
        print("\n=== All UL elements on page ===")
        all_uls = soup.find_all('ul')
        print(f"Total <ul> elements on page: {len(all_uls)}")

        for idx, ul in enumerate(all_uls[:10]):  # Show first 10
            li_count = len(ul.find_all('li'))
            ul_classes = ' '.join(ul.get('class', []))
            print(f"  UL {idx}: {li_count} <li> items, classes: {ul_classes}")

            if li_count > 0 and li_count < 20:  # Likely schedule-related
                print(f"    Sample text: {ul.get_text(strip=True)[:150]}")

        print("\n" + "=" * 80)

    except Exception as e:
        print(f"Debug error: {e}")


# Main execution example
if __name__ == "__main__":
    # Example usage
    # url = "https://www.formula1.com/en/racing/2026/australia"
    url = "https://www.formula1.com/en/racing/2026/china"
    print("Extracting F1 schedule...")
    print("=" * 80)

    # Uncomment to debug page structure:
    # debug_page_structure(url)

    # Extract the schedule
    schedule = extract_f1_schedule(url)

    if schedule:
        print(f"\n✓ Successfully extracted schedule for {schedule['race_name']} {schedule['year']}")
        print(f"  Found {len(schedule['sessions'])} sessions\n")

        print(f"{'#':<3} {'Session':<20} {'DateTime Local':<20} {'DateTime UTC':<20}")
        print("-" * 70)

        for idx, session in enumerate(schedule['sessions'], 1):
            session_name = session.get('session_name', 'Unknown')
            dt_local = session.get('datetime_local', 'TBD')
            dt_utc = session.get('datetime_utc', 'TBD')
            print(f"{idx:<3} {session_name:<20} {dt_local:<20} {dt_utc:<20}")

        # Save to JSON
        # save_schedule_to_json(schedule, 'f1_schedule_australia_2026.json')
        print("\n" + "=" * 80)
    else:
        print("Failed to extract schedule")

