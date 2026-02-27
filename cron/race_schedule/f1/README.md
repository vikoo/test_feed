# F1 Schedule Extraction Utility

This module provides utilities to extract Formula 1 race schedules from the official Formula1.com website.

## Features

- Extract race schedules from Formula1.com race pages
- Parse session information including dates and times
- **Automatic UTC time conversion** based on race location
- Support for Practice, Qualifying, Sprint, and Race sessions
- Export schedule data to JSON format
- Debug utilities to inspect page structure

## Installation

The script requires the following Python packages:
```bash
pip install requests beautifulsoup4
```

These are already included in the project's `requirements.txt`.

## Usage

### Basic Usage

```python
from f1_schedule_utils import extract_f1_schedule

# Extract schedule from a race URL
url = "https://www.formula1.com/en/racing/2026/australia"
schedule = extract_f1_schedule(url)

# Access the data
print(f"Year: {schedule['year']}")
print(f"Race: {schedule['race_name']}")
print(f"Sessions: {len(schedule['sessions'])}")

# Iterate through sessions
for idx, session in enumerate(schedule['sessions'], 1):
    session_name = session['session_name']
    dt_local = session.get('datetime_local', 'TBD')
    dt_utc = session.get('datetime_utc', 'TBD')
    print(f"{idx}. {session_name}: {dt_local} (local) / {dt_utc} (UTC)")
```
```
```

### Save to JSON

```python
from f1_schedule_utils import extract_f1_schedule, save_schedule_to_json

url = "https://www.formula1.com/en/racing/2026/australia"
schedule = extract_f1_schedule(url)
save_schedule_to_json(schedule, 'australia_2026.json')
```

### Debug Page Structure

```python
from f1_schedule_utils import debug_page_structure

url = "https://www.formula1.com/en/racing/2026/australia"
debug_page_structure(url)
```

## UTC Time Conversion

The script automatically converts all session times from local race timezone to UTC and combines them with the date. This creates complete datetime stamps for easy scheduling and comparison.

### Features:
- **Combined DateTime**: Date and time are merged into a single field (e.g., "2026-03-08 04:00")
- **Start Times Only**: For time ranges (e.g., "01:30-02:30"), only the start time is used
- **UTC Conversion**: Based on built-in timezone map for all F1 race locations
- **Date Adjustment**: Automatically handles day changes when converting timezones

### Timezone Map:
- **Australia**: UTC+11 (Melbourne AEDT during March)
- **Bahrain**: UTC+3
- **China**: UTC+8
- **Japan**: UTC+9
- **Monaco**: UTC+2 (CEST)
- **United States** (Austin): UTC-5 (CDT)
- **Miami**: UTC-4 (EDT)
- **Abu Dhabi**: UTC+4
- And many more...

### Example:
```
Practice 1 in Australia:
  Local:  2026-03-06 01:30  (AEDT, UTC+11)
  UTC:    2026-03-05 14:30  (Previous day!)
  
Race in Miami:
  Local:  2026-05-03 20:00  (EDT, UTC-4)
  UTC:    2026-05-04 00:00  (Next day!)
```

If a race location is not in the timezone map, times will default to UTC (no conversion).

## Schedule Data Structure

The `extract_f1_schedule()` function returns a dictionary with the following structure:

```json
{
  "url": "https://www.formula1.com/en/racing/2026/australia",
  "year": "2026",
  "race_name": "Australia",
  "extracted_at": "2026-02-27T14:00:00.000000",
  "sessions": [
    {
      "session_name": "Practice 1",
      "datetime_local": "2026-03-06 01:30",
      "datetime_utc": "2026-03-05 14:30",
      "raw_text": "06MarPractice 101:30-02:30",
      "classes": "...",
      "data_attributes": {...}
    },
    {
      "session_name": "Race",
      "datetime_local": "2026-03-08 04:00",
      "datetime_utc": "2026-03-07 17:00",
      "raw_text": "08MarRace04:00",
      "classes": "...",
      "data_attributes": {...}
    }
  ]
}
```

### Session Object Fields

- `session_name`: Name of the session (e.g., "Practice 1", "Qualifying", "Race")
- `datetime_local`: Combined date and start time in local race timezone (format: "YYYY-MM-DD HH:MM")
- `datetime_utc`: Combined date and start time converted to UTC (format: "YYYY-MM-DD HH:MM")
- `raw_text`: Raw text extracted from the HTML element
- `classes`: CSS classes of the HTML element
- `data_attributes`: Any HTML data attributes
- `datetime_iso`: ISO datetime if available in the HTML

**Note**: Only start times are included. For sessions with time ranges (e.g., "01:30-02:30"), only the start time ("01:30") is extracted and combined with the date.

## Functions

### `extract_f1_schedule(url)`

Extract the F1 schedule from a Formula1.com race page.

**Parameters:**
- `url` (str): The URL of the F1 race page (e.g., https://www.formula1.com/en/racing/2026/australia)

**Returns:**
- `dict`: Dictionary containing the extracted schedule information

### `extract_f1_schedule_detailed(url)`

Extract schedule with more detailed parsing including HTML structure.

**Parameters:**
- `url` (str): The URL of the F1 race page

**Returns:**
- `dict`: Detailed schedule information with HTML structure

### `save_schedule_to_json(schedule_data, output_file)`

Save the extracted schedule to a JSON file.

**Parameters:**
- `schedule_data` (dict): The schedule data to save
- `output_file` (str): The output file path (default: 'f1_schedule.json')

### `print_schedule(schedule_data)`

Print the extracted schedule in a readable format.

**Parameters:**
- `schedule_data` (dict): The schedule data to print

### `debug_page_structure(url)`

Debug function to inspect the page structure and find schedule elements.

**Parameters:**
- `url` (str): The URL to inspect

### `parse_race_url(url)`

Parse the Formula1.com race URL to extract year and race name.

**Parameters:**
- `url` (str): URL like https://www.formula1.com/en/racing/2026/australia

**Returns:**
- `dict`: Dictionary with 'year' and 'race_name' keys

### `get_timezone_offset_for_race(race_name)`

Get the UTC offset for a race location.

**Parameters:**
- `race_name` (str): Name of the race location

**Returns:**
- `int`: UTC offset in hours (positive or negative)

### `convert_time_to_utc(local_time, date_str, year, race_name)`

Convert local race time to UTC.

**Parameters:**
- `local_time` (str): Time in format "HH:MM" or "HH:MM-HH:MM"
- `date_str` (str): Date in format "DDMon" (e.g., "06Mar")
- `year` (str): Year as string
- `race_name` (str): Name of the race location for timezone detection

**Returns:**
- `str`: UTC time(s) in same format as input, or None if conversion fails

## Example: Extract Multiple Races

```python
from f1_schedule_utils import extract_f1_schedule

races = [
    "https://www.formula1.com/en/racing/2026/australia",
    "https://www.formula1.com/en/racing/2026/bahrain",
    "https://www.formula1.com/en/racing/2026/saudi-arabia"
]

for race_url in races:
    schedule = extract_f1_schedule(race_url)
    if schedule:
        print(f"\n{schedule['race_name']} {schedule['year']}")
        print("-" * 60)
        for session in schedule['sessions']:
            local = session.get('time_local', 'TBD')
            utc = session.get('time_utc', 'TBD')
            print(f"  {session['session_name']}: {session.get('date', 'TBD')} | Local: {local} | UTC: {utc}")
```

## Testing

Run the test script to verify the extraction works:

```bash
python test_extraction.py
```

## Notes

- The script uses BeautifulSoup to parse HTML from Formula1.com
- It looks for schedule data in `<ul>` elements with grid layout classes
- The extraction is based on the current HTML structure of Formula1.com (as of February 2026)
- If the website structure changes, the selectors may need to be updated

## Troubleshooting

If the schedule is not being extracted:

1. Run the debug function to see the page structure:
   ```python
   from f1_schedule_utils import debug_page_structure
   debug_page_structure(url)
   ```

2. Check if the URL is correct and accessible

3. Verify that the page contains schedule information (some future races may not have schedules published yet)

4. The website might be using JavaScript to load content dynamically. If so, you may need to use Selenium or similar tools.

## Integration with Project

This utility is part of the PS Feed Upload project and follows the same patterns as the MotoGP schedule utilities in `cron/race_schedule/moto_gp/`.

