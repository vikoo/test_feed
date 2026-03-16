"""
GP Upload Script

Orchestrates data fetching for the F1 Grand Prix upload pipeline:

    Step 1 — Fetch all seasons   → { year: season_id }
    Step 2 — Fetch all tracks    → { location: track_id }
    Step 3 — Fetch F1 schedule   → list of GP events (FastF1)
    Step 4 — Build GP payload    → JSON array ready for POST /api/grands-prix/bulk

Each step is logged clearly. The combined data is then available for
further processing / uploading to the PS Backend.
"""

import re
import sys
import os
import json as _json

# Ensure the project root (test_feed/) is on sys.path when running directly.
sys.path.insert(
    0,
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
)

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from loguru import logger

from cron.server_v2.ps_backend.seasons.ps_seasons import fetch_all_seasons
from cron.server_v2.ps_backend.tracks.ps_tracks import fetch_tracks_location_id_map
from cron.server_v2.fast_f1.fast_f1_schedule import fetch_f1_schedule
from cron.server_v2.ps_backend.utils.common_utils import (
    make_ps_api_request,
    safe_get,
    APIError,
)


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def step_fetch_seasons() -> Dict[str, int]:
    """
    Step 1 — Fetch all seasons from the PS Backend.

    Returns:
        Dict[str, int]: { year_str: season_id }
            Example: {'2024': 2, '2025': 3, '2026': 4}
    """
    logger.info("─" * 50)
    logger.info("STEP 1 — Fetching all seasons...")
    logger.info("─" * 50)

    seasons = fetch_all_seasons()

    logger.info(f"✓ Seasons fetched: {len(seasons)} entries")
    for year in sorted(seasons.keys()):
        logger.debug(f"   Year {year} → Season ID {seasons[year]}")

    return seasons


def step_fetch_tracks() -> Dict[str, int]:
    """
    Step 2 — Fetch all tracks from the PS Backend.

    Returns:
        Dict[str, int]: { location: track_id }
            Example: {'Sakhir': 1, 'Monza': 5, 'Monte Carlo': 8}
    """
    logger.info("─" * 50)
    logger.info("STEP 2 — Fetching all tracks...")
    logger.info("─" * 50)

    tracks = fetch_tracks_location_id_map()

    logger.info(f"✓ Tracks fetched: {len(tracks)} entries")
    for location, track_id in list(tracks.items())[:5]:
        logger.debug(f"   '{location}' → Track ID {track_id}")
    if len(tracks) > 5:
        logger.debug(f"   ... and {len(tracks) - 5} more")

    return tracks


def step_fetch_f1_schedule(year: int) -> List[Dict[str, Any]]:
    """
    Step 3 — Fetch the F1 race schedule for the given year via FastF1.

    Args:
        year (int): Championship year to fetch (e.g. 2026).

    Returns:
        List[Dict]: List of GP event dicts from fast_f1_schedule.fetch_f1_schedule().
    """
    logger.info("─" * 50)
    logger.info(f"STEP 3 — Fetching F1 schedule for {year}...")
    logger.info("─" * 50)

    schedule = fetch_f1_schedule(year)

    logger.info(f"✓ F1 schedule fetched: {len(schedule)} events for {year}")
    for event in schedule:
        sprint_flag = " [SPRINT]" if event.get("is_sprint") else ""
        logger.debug(
            f"   Round {event['round_number']:>2}: {event['event_name']}"
            f" ({event['location']}, {event['country']}){sprint_flag}"
        )

    return schedule


# ---------------------------------------------------------------------------
# Step 4 helpers
# ---------------------------------------------------------------------------

# Suffixes that end GP names — we strip these before appending the short year
_GP_SUFFIX_RE = re.compile(
    r"\s*(grand\s+prix|gp)\s*$",
    re.IGNORECASE,
)


def _format_gp_name(event_name: str, year: int) -> str:
    """
    Convert a full event name into the short GP name with year suffix.

    Rules:
        • Strip trailing "Grand Prix" / "GP" (case-insensitive)
        • Append "GP <2-digit year>"

    Examples:
        "Las Vegas Grand Prix"  → "Las Vegas GP 26"
        "São Paulo Grand Prix"  → "São Paulo GP 26"
        "Monaco GP"             → "Monaco GP 26"
    """
    short_year = str(year)[-2:]
    base = _GP_SUFFIX_RE.sub("", event_name).strip()
    return f"{base} GP {short_year}"


def _make_slug(name: str) -> str:
    """
    Turn a GP name into a URL-safe, hyphen-separated slug.

    Example:
        "Las Vegas GP 26" → "las-vegas-gp-26"
    """
    # Normalise: lowercase, replace non-alphanumeric runs with a hyphen
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def _parse_utc(date_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 UTC string into a timezone-aware datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def step_build_gp_payload(
    schedule: List[Dict[str, Any]],
    seasons: Dict[str, int],
    tracks: Dict[str, int],
    year: int,
) -> List[Dict[str, Any]]:
    """
    Step 4 — Map the FastF1 schedule into the bulk-upload payload for
    POST /api/grands-prix/bulk.

    Field mapping (camelCase — matches POST /api/grands-prix/bulk)
    ──────────────────────────────────────────────────────────────
    name          → "<location> GP <YY>"  (e.g. "Las Vegas GP 26")
    slug          → hyphen-separated name  (e.g. "las-vegas-gp-26")
    officialName  → circuit_name
    seasonId      → seasons[str(year)]
    round         → round_number
    startDate     → sessions[0].date_utc
    endDate       → sessions[-1].date_utc + 2 hours
    laps          → total_laps (0 if null)
    length        → track_length_km
    distance      → laps * length
    isSprint      → is_sprint
    trackId       → tracks[location]  (None-safe)
    gpType        → "Sprint" if is_sprint else "Normal"

    Args:
        schedule  : List of event dicts from fetch_f1_schedule().
        seasons   : { year_str: season_id } from fetch_all_seasons().
        tracks    : { location: track_id } from fetch_tracks_location_id_map().
        year      : Championship year (used for season lookup + name suffix).

    Returns:
        List[Dict[str, Any]]: Ready-to-POST GP payload array.
    """
    logger.info("─" * 50)
    logger.info("STEP 4 — Building GP upload payload...")
    logger.info("─" * 50)

    season_id: Optional[int] = seasons.get(str(year))
    if season_id is None:
        logger.warning(f"No season found for year {year} — season_id will be null")

    payload: List[Dict[str, Any]] = []
    skipped = 0

    for event in schedule:
        event_name      = event.get("event_name", "")
        location        = event.get("location", "")
        round_number    = event.get("round_number")
        circuit_name    = event.get("circuit_name", "")
        sessions        = event.get("sessions", [])
        is_sprint       = any(s.get("name") == "Sprint" for s in sessions)
        total_laps_raw  = event.get("total_laps")
        track_length    = event.get("track_length_km")

        # ── Derived name & slug ───────────────────────────────────────────────
        name = _format_gp_name(event_name, year)
        slug = _make_slug(name)

        # ── Dates ─────────────────────────────────────────────────────────────
        # Filter only sessions that have a valid date
        dated_sessions = [s for s in sessions if s.get("date_utc")]

        start_date: Optional[str] = None
        end_date: Optional[str] = None

        if dated_sessions:
            start_dt = _parse_utc(dated_sessions[0]["date_utc"])
            end_dt   = _parse_utc(dated_sessions[-1]["date_utc"])

            if start_dt:
                start_date = start_dt.isoformat()
            if end_dt:
                end_date = (end_dt + timedelta(hours=2)).isoformat()

        # ── Numeric fields ────────────────────────────────────────────────────
        # API constraints: laps minimum=1, distance/length exclusiveMinimum=0
        # → omit these fields entirely when the value is unknown/zero rather
        #   than sending 0 (which would fail validation).
        laps:     Optional[int]   = int(total_laps_raw) if total_laps_raw is not None and int(total_laps_raw) >= 1 else None
        length:   Optional[float] = track_length if track_length and track_length > 0 else None
        distance: Optional[float] = round(laps * length, 3) if (laps and length) else None

        # ── Lookups ───────────────────────────────────────────────────────────
        track_id: Optional[int] = tracks.get(location)
        if track_id is None:
            logger.error(
                f"Round {round_number}: No track_id found for location '{location}' — track_id will be null"
            )

        gp_type = "Sprint" if is_sprint else "Normal"

        # Build the GP dict, omitting None-valued optional numeric fields so
        # the API does not receive 0 / null where it expects a positive integer.
        gp: Dict[str, Any] = {
            "name":         name,
            "slug":         slug,
            "officialName": circuit_name,
            "seasonId":     season_id,
            "round":        round_number,
            "startDate":    start_date,
            "endDate":      end_date,
            "isSprint":     is_sprint,
            "trackId":      track_id,
            "gpType":       gp_type,
        }
        if laps is not None:
            gp["laps"] = laps
        if length is not None:
            gp["length"] = length
        if distance is not None:
            gp["distance"] = distance

        payload.append(gp)
        logger.debug(
            f"  Round {round_number:>2}: {name} | track_id={track_id} | "
            f"season_id={season_id} | {laps} laps × {length} km = {distance} km | {gp_type}"
        )

    logger.info(f"✓ GP payload built: {len(payload)} entries  ({skipped} skipped)")
    return payload


# ---------------------------------------------------------------------------
# Step 5 — Upload
# ---------------------------------------------------------------------------

# The bulk endpoint accepts a maximum of 50 GPs per request.
_BULK_CHUNK_SIZE = 50


def step_upload_gp_payload(
    gp_payload: List[Dict[str, Any]],
) -> list[Any] | tuple[list | list[Any], dict[int, int]] | tuple[list[Any], dict[Any, Any]]:
    """
    Step 5 — Upload the GP payload to POST /api/grands-prix/bulk.

    Sends all records in a single atomic request.
    The API enforces a hard limit of 50 items per request; if the payload
    exceeds this a ValueError is raised early so the caller can split manually.

    API contract (from schema):
        POST  /api/grands-prix/bulk
        Body  { "grandsPrix": [ ...gp_objects... ] }
        Auth  Bearer token (required)
        201   { "success": true, "data": { "created": [...] } }

    Args:
        gp_payload: List of GP dicts produced by step_build_gp_payload().

    Returns:
        Tuple[List[Dict[str, Any]], Dict[int, int]]:
            - List of successfully created GP objects.
            - Dict mapping round number → GP id  (e.g. {1: 101, 2: 102, ...})

    Raises:
        ValueError: If payload exceeds the API's 50-item limit.
        APIError: If the request fails.
    """
    logger.info("─" * 50)
    logger.info("STEP 5 — Uploading GP payload to API...")
    logger.info(f"  Endpoint : POST /api/grands-prix/bulk")
    logger.info(f"  Records  : {len(gp_payload)}")
    logger.info("─" * 50)

    if not gp_payload:
        logger.warning("GP payload is empty — nothing to upload")
        return []

    if len(gp_payload) > _BULK_CHUNK_SIZE:
        raise ValueError(
            f"Payload has {len(gp_payload)} records but the API accepts at most "
            f"{_BULK_CHUNK_SIZE} per request."
        )


    logger.info("GP Payload (pre-upload):")
    logger.info(_json.dumps(gp_payload, indent=2, ensure_ascii=False))

    try:
        response = make_ps_api_request(
            endpoint="/api/grands-prix/bulk",
            method="POST",
            data={"grandsPrix": gp_payload},
            timeout=60,
        )

        created = safe_get(response, "data", "created", default=[])
        if not isinstance(created, list):
            created = []

        round_id_map: Dict[int, int] = {
            safe_get(gp, "round"): safe_get(gp, "id")
            for gp in created
            if safe_get(gp, "round") is not None and safe_get(gp, "id") is not None
        }

        logger.info("=" * 50)
        logger.info(f"✓ Upload complete: {len(created)} GPs created")
        logger.info("=" * 50)
        for gp in created:
            logger.debug(
                f"  → ID={safe_get(gp, 'id')} | "
                f"Round {safe_get(gp, 'round'):>2} | "
                f"{safe_get(gp, 'name')}"
            )
        logger.debug(f"  Round→ID map: {round_id_map}")

        return created, round_id_map

    except APIError as e:
        # 409 Conflict → GPs already exist in the database (idempotent re-run).
        # Treat this as success: log a warning and return empty list.
        if "409" in str(e):
            logger.warning(
                "⚠ 409 Conflict — GPs already exist for this season. "
                "Skipping upload (records already in DB)."
            )
            return [], {}
        logger.error(f"✗ Upload failed: {e}")
        raise



# ---------------------------------------------------------------------------
# Step 6 — Upload GP Sessions
# ---------------------------------------------------------------------------

# The sessions bulk endpoint also enforces a maximum of 50 items per request.
_SESSION_BULK_CHUNK_SIZE = 50

# Session type mapping from FastF1 name → PS Backend enum
_SESSION_TYPE_MAP: Dict[str, str] = {
    "Practice 1":       "FP1",
    "Practice 2":       "FP2",
    "Practice 3":       "FP3",
    "Qualifying":       "Q1",
    "Race":             "RACE",
    "Sprint":           "SPRINT",
    "Sprint Shootout":  "SQ1",
    "Sprint Qualifying": "SQ1"
}


def upload_gp_sessions(
    f1_schedule: List[Dict[str, Any]],
    round_id_map: Dict[int, int],
) -> List[Dict[str, Any]]:
    """
    Step 6 — Build and upload GP sessions payload to POST /api/sessions/bulk.

    For each event in the F1 schedule, maps every session to the PS Backend
    session type.  Extra dummy Q2/Q3 and SQ2/SQ3 sessions are appended after
    Qualifying / Sprint Shootout respectively.

    The API enforces a hard limit of 50 sessions per request; the full payload
    is automatically split into chunks of _SESSION_BULK_CHUNK_SIZE (50) and
    sent in sequential requests.  Results from all chunks are merged and
    returned as a single flat list.

    Type mapping
    ────────────
    Practice 1      → FP1
    Practice 2      → FP2
    Practice 3      → FP3
    Qualifying      → Q1  (+Q2 at Q1+15 min, +Q3 at Q1+30 min)
    Race            → RACE
    Sprint          → SPRINT
    Sprint Shootout → SQ1 (+SQ2 at SQ1+15 min, +SQ3 at SQ1+30 min)

    Args:
        f1_schedule   : List of event dicts from fetch_f1_schedule().
        round_id_map  : { round_number: gp_id } from step_upload_gp_payload().

    Returns:
        List of created session objects returned by the API.
    """
    logger.info("─" * 50)
    logger.info("STEP 6 — Building & uploading GP sessions payload...")
    logger.info("─" * 50)

    sessions_payload: List[Dict[str, Any]] = []

    for event in f1_schedule:
        round_number = event.get("round_number")
        gp_id = round_id_map.get(round_number)

        if gp_id is None:
            logger.warning(
                f"Round {round_number}: No GP id found in round_id_map — skipping sessions"
            )
            continue

        for session in event.get("sessions", []):
            session_name = session.get("name", "")
            date_utc     = session.get("date_utc")
            session_type = _SESSION_TYPE_MAP.get(session_name)

            if session_type is None:
                logger.warning(
                    f"Round {round_number}: Unknown session name '{session_name}' — skipping"
                )
                continue

            sessions_payload.append({
                "grandPrixId":   gp_id,
                "type":          session_type,
                "scheduledStart": date_utc,
            })

            # ── Extra Q2 / Q3 after Qualifying ────────────────────────────
            if session_name == "Qualifying" and date_utc:
                q1_dt = _parse_utc(date_utc)
                if q1_dt:
                    sessions_payload.append({
                        "grandPrixId":    gp_id,
                        "type":           "Q2",
                        "scheduledStart": (q1_dt + timedelta(minutes=15)).isoformat(),
                    })
                    sessions_payload.append({
                        "grandPrixId":    gp_id,
                        "type":           "Q3",
                        "scheduledStart": (q1_dt + timedelta(minutes=30)).isoformat(),
                    })

            # ── Extra SQ2 / SQ3 after Sprint Shootout ─────────────────────
            if (session_name == "Sprint Shootout" or session_name == "Sprint Qualifying") and date_utc:
                sq1_dt = _parse_utc(date_utc)
                if sq1_dt:
                    sessions_payload.append({
                        "grandPrixId":    gp_id,
                        "type":           "SQ2",
                        "scheduledStart": (sq1_dt + timedelta(minutes=15)).isoformat(),
                    })
                    sessions_payload.append({
                        "grandPrixId":    gp_id,
                        "type":           "SQ3",
                        "scheduledStart": (sq1_dt + timedelta(minutes=30)).isoformat(),
                    })

    logger.info(f"  Sessions payload built: {len(sessions_payload)} records")
    logger.info(_json.dumps(sessions_payload, indent=2, ensure_ascii=False))

    if not sessions_payload:
        logger.warning("Sessions payload is empty — nothing to upload")
        return []

    # ── Chunk the payload into batches of _SESSION_BULK_CHUNK_SIZE ────────────
    chunks = [
        sessions_payload[i: i + _SESSION_BULK_CHUNK_SIZE]
        for i in range(0, len(sessions_payload), _SESSION_BULK_CHUNK_SIZE)
    ]
    total_chunks = len(chunks)
    logger.info(
        f"  Uploading {len(sessions_payload)} sessions in "
        f"{total_chunks} chunk(s) of up to {_SESSION_BULK_CHUNK_SIZE}..."
    )

    all_created: List[Dict[str, Any]] = []

    for chunk_idx, chunk in enumerate(chunks, start=1):
        logger.info(_json.dumps(chunks, indent=2, ensure_ascii=False))
        logger.info(f"  → Chunk {chunk_idx}/{total_chunks}: {len(chunk)} sessions")
        try:
            response = make_ps_api_request(
                endpoint="/api/sessions/bulk",
                method="POST",
                data={"sessions": chunk},
                timeout=60,
            )

            created = response.get("data", [])
            if not isinstance(created, list):
                created = []

            all_created.extend(created)
            logger.info(f"    ✓ Chunk {chunk_idx} complete: {len(created)} sessions created")

        except APIError as e:
            if "409" in str(e):
                logger.warning(
                    f"    ⚠ Chunk {chunk_idx} — 409 Conflict: Sessions already exist. "
                    "Skipping chunk (records already in DB)."
                )
                continue
            logger.error(f"    ✗ Chunk {chunk_idx} failed: {e}")
            raise

    logger.info("=" * 50)
    logger.info(f"✓ Sessions upload complete: {len(all_created)} sessions created")
    logger.info("=" * 50)
    for s in all_created:
        logger.debug(
            f"  → ID={safe_get(s, 'id')} | GP={safe_get(s, 'grandPrixId')} | "
            f"Type={safe_get(s, 'type')} | Start={safe_get(s, 'scheduledStart')}"
        )

    return all_created


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_gp_upload(year: int = datetime.now().year):
    """
    Main entry point — runs all five steps in sequence.

    Args:
        year (int): Championship year for the F1 schedule. Defaults to current year.

    Returns:
        tuple: (seasons, tracks, f1_schedule, gp_payload, created_gps)
    """
    logger.info("=" * 50)
    logger.info("GP Upload — Data Fetch & Upload Pipeline")
    logger.info(f"Year: {year}")
    logger.info("=" * 50)

    # Step 1 — Seasons
    ps_seasons = step_fetch_seasons()

    # Step 2 — Tracks
    ps_tracks = step_fetch_tracks()

    # Step 3 — F1 Schedule
    f1_schedule = step_fetch_f1_schedule(year)
    logger.info(f"f1 schedule: {f1_schedule}")
    logger.info(f"f1 schedule: {_json.dumps(f1_schedule, indent=2, ensure_ascii=False)}")

    # Step 4 — Build GP payload
    gp_payload = step_build_gp_payload(f1_schedule, ps_seasons, ps_tracks, year)

    # Step 5 — Upload to API
    created_gps, round_id_map = step_upload_gp_payload(gp_payload)

    # Step 6 — Upload GP sessions
    created_sessions = upload_gp_sessions(f1_schedule, round_id_map)

    # Summary
    logger.info("=" * 50)
    logger.info("Pipeline complete — Summary")
    logger.info("=" * 50)
    logger.info(f"  Seasons          : {len(ps_seasons)} entries")
    logger.info(f"  Tracks           : {len(ps_tracks)} entries")
    logger.info(f"  F1 Schedule      : {len(f1_schedule)} events ({year})")
    logger.info(f"  GP Payload       : {len(gp_payload)} records built")
    logger.info(f"  GPs Created      : {len(created_gps)} records uploaded")
    logger.info(f"  Round→ID map     : {round_id_map}")
    logger.info(f"  Sessions Created : {len(created_sessions)} sessions uploaded")
    logger.info("=" * 50)

    return ps_seasons, ps_tracks, f1_schedule, gp_payload, created_gps, round_id_map


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Optional: pass year as CLI argument, e.g. python gp_upload.py 2026
    _year = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().year
    _year = 2026

    try:
        run_gp_upload(year=_year)
    except APIError as e:
        logger.error(f"API Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

