"""Post-session corrections from the official FIM PDFs, run by the weekend runner.

Replaces two manual mz-ops steps:
1. Starting grid (scripts/audit_starting_grid.py). The uploader guesses grid slots from the Q1 order and
   ignores grid penalties. The FIM Grid PDF of the finished Sprint and Race is the reference. App and stats
   convention: Race slot = finalPos ?? position, Sprint slot = sprintFinalPos ?? finalPos ?? position, over
   Q2 rows and Q1 rows with position > 2. Riders who qualified but are not on the official grid are placed
   after the starters in qualifying order.
2. Sprint fastest lap. The API has no Sprint fastest-lap record; the Sprint Classification PDF has the line
   "Fastest Lap: Lap N Rider NAME 1'29.752". Set only when no Sprint row carries the flag yet.

Every PDF is checked before use (enough distinct riders on a grid, a parsable fastest-lap line, a rider
that matches the API classification). Anything doubtful is left alone and reported, never guessed.
Needs `pdftotext` (poppler-utils).
"""
import os
import re
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

PULSELIVE = "https://api.motogp.pulselive.com/motogp/v1/results"
CATEGORY_MOTOGP = "e8c110ad-64aa-4e8e-8a86-f2f152f6a942"

# "89JorgeMARTIN" (2025/2026 layout) and "89 Jorge MARTIN" (2024 layout); lap times and "21 laps" do not match.
_GRID_ROW = re.compile(r"^(\d{1,2}) ?[A-Z][a-zà-ÿ'.-]+ ?[A-ZÀ-Ý]", re.M)
_FASTEST_LAP = re.compile(r"Fastest Lap(?: \([^)]*\))?:\s+Lap\s+(\d+)\s+(.+?)\s{2,}(\d+'\d\d\.\d{3})")

# How long after a Sprint or Race start a missing PDF still counts as "not published yet".
PENDING_HOURS = 8
_state = {}  # gp id -> {"last": datetime, "pending": bool}


def pdf_text(url: str, layout: str) -> str:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
    r.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(r.content)
        f.flush()
        out = subprocess.run(["pdftotext", f"-{layout}", f.name, "-"], capture_output=True, text=True, timeout=60)
    return out.stdout


def parse_grid_text(text: str) -> list:
    return [int(m.group(1)) for m in _GRID_ROW.finditer(text)]


def parse_fastest_lap(text: str):
    """(lap number, rider name as printed, time "1'29.752") or None."""
    for line in text.splitlines():
        if "Fastest Lap" in line:
            m = _FASTEST_LAP.search(line)
            if m:
                return int(m.group(1)), m.group(2).strip(), m.group(3)
    return None


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def final_session(sessions: list, api_type: str):
    """The session that carries the result: for a red-flag restart the API lists RAC and RAC 2."""
    cands = [s for s in sessions if s.get("type") == api_type]
    return max(cands, key=lambda s: s.get("number") or 1) if cands else None


def official_grid(session) -> tuple:
    """(rider numbers in grid order, note). None when the PDF is missing or not readable."""
    if not session or session.get("status") != "FINISHED":
        return None, "session not finished"
    url = ((session.get("session_files") or {}).get("grid") or {}).get("url")
    if not url:
        return None, "no grid PDF listed"
    nums = parse_grid_text(pdf_text(url, "raw"))
    if len(nums) < 10 or len(set(nums)) != len(nums):
        return None, f"grid PDF not readable ({len(nums)} riders, {len(set(nums))} distinct)"
    return nums, "ok"


def plan_grid(q_rows: list, grids: dict) -> list:
    """Field changes [(row_id, field, new, why)] that make the stored grid equal the official grids.
    q_rows: [{"id", "type" ("QNR1"/"QNR2"), "number", "position", "finalPos", "sprintFinalPos"}]."""
    cur = {r["number"]: r for r in q_rows if r["type"] == "QNR2" or (r["position"] or 0) > 2}
    qorder = sorted(cur, key=lambda n: (cur[n]["position"] or 99) + (10 if cur[n]["type"] == "QNR1" else 0))
    plan, new_race = [], {}
    for kind in ("Race", "Sprint"):
        g = grids.get(kind)
        if g is None:
            continue
        want = {n: i + 1 for i, n in enumerate(g)}
        for k, n in enumerate([n for n in qorder if n not in want]):
            want[n] = len(g) + 1 + k
        for n, c in cur.items():
            race_stored = c["finalPos"] if c["finalPos"] is not None else c["position"]
            if kind == "Race":
                new_race[n] = want[n]
                if race_stored != want[n]:
                    plan.append((c["id"], "finalPos", want[n], f"#{n} Race grid {race_stored} -> {want[n]}"))
            else:
                race_slot = new_race.get(n, race_stored)
                stored = c["sprintFinalPos"] if c["sprintFinalPos"] is not None else race_stored
                if stored != want[n] or (c["sprintFinalPos"] is None and race_slot != want[n]):
                    plan.append((c["id"], "sprintFinalPos", want[n], f"#{n} Sprint grid {stored} -> {want[n]}"))
    return plan


def sprint_fastest_lap(session, classification: list):
    """(rider number, lap, time) from the Sprint Classification PDF, or (None, note)."""
    if not session or session.get("status") != "FINISHED":
        return None, "Sprint not finished"
    url = ((session.get("session_files") or {}).get("classification") or {}).get("url")
    if not url:
        return None, "no classification PDF listed"
    fl = parse_fastest_lap(pdf_text(url, "layout"))
    if not fl:
        return None, "no fastest lap line in the PDF"
    lap, name, time = fl
    matches = [c["rider"]["number"] for c in classification if _norm(c["rider"].get("full_name")) == _norm(name)]
    if len(matches) != 1:
        return None, f"fastest lap rider {name!r} not matched in the classification"
    return (matches[0], lap, time), "ok"


def _rows(fetch_rows, gp_id):
    out = []
    for r in fetch_rows(gp_id):
        a = r["attributes"]
        out.append({"id": r["id"], "type": a["race"]["data"]["attributes"]["type"],
                    "number": a["seasonGrid"]["data"]["attributes"]["driverNumber"],
                    "position": a.get("position"), "finalPos": a.get("finalPos"),
                    "sprintFinalPos": a.get("sprintFinalPos"), "fastestLap": a.get("fastestLap")})
    return out


def run_gp(gp: dict, started: dict, now: datetime, api, fetch_rows, write, apply: bool = True):
    """Corrections for one Grand Prix. `started` = {"Sprint": datetime, "Race": datetime} of the sessions
    that have started. Returns (changed, pending, problems). `api(path)` returns pulselive JSON."""
    changed, pending, problems = False, [], []
    label = gp["shortName"]
    season = next(s for s in api("seasons") if str(s["year"]) == str(gp["year"]))
    event = next((e for e in api(f"events?seasonUuid={season['id']}") if e.get("short_name") == gp["shortName"]), None)
    if not event:
        return False, [], [f"{label}: event not found in the MotoGP API"]
    sessions = api(f"sessions?eventUuid={event['id']}&categoryUuid={CATEGORY_MOTOGP}")
    rows = _rows(fetch_rows, gp["id"])

    def note(kind, msg):
        fresh = kind in started and now - started[kind] < timedelta(hours=PENDING_HOURS)
        (pending if fresh else problems).append(f"{label} {kind}: {msg}")

    grids = {}
    for kind, api_type in (("Sprint", "SPR"), ("Race", "RAC")):
        if kind not in started:
            continue
        try:
            nums, msg = official_grid(final_session(sessions, api_type))
        except Exception as e:
            nums, msg = None, f"grid PDF failed: {type(e).__name__}: {e}"
        if nums:
            grids[kind] = nums
        else:
            note(kind, msg)
    q_rows = [r for r in rows if r["type"] in ("QNR1", "QNR2")]
    plan = plan_grid(q_rows, grids) if q_rows and grids else []
    for row_id, field, new, why in plan:
        logger.info(f"{label} grid fix {why} (row {row_id})")
        if apply:
            write(row_id, {field: new})
        changed = True

    if "Sprint" in started:
        sprint_rows = [r for r in rows if r["type"] == "Sprint"]
        if sprint_rows and not any(r["fastestLap"] for r in sprint_rows):
            spr = final_session(sessions, "SPR")
            try:
                cls = api(f"session/{spr['id']}/classification?test=false").get("classification") or [] if spr else []
                fl, msg = sprint_fastest_lap(spr, cls)
            except Exception as e:
                fl, msg = None, f"fastest lap PDF failed: {type(e).__name__}: {e}"
            if fl:
                num, lap, time = fl
                row = next((r for r in sprint_rows if r["number"] == num), None)
                if row:
                    logger.info(f"{label} Sprint fastest lap #{num} lap {lap} {time} (row {row['id']})")
                    if apply:
                        write(row["id"], {"fastestLap": True, "fastestLapNo": lap, "fastestLapTime": time})
                    changed = True
                else:
                    problems.append(f"{label} Sprint: fastest lap rider #{num} has no Sprint row")
            else:
                note("Sprint", msg)
    return changed, pending, problems


def pulselive(path: str):
    r = requests.get(f"{PULSELIVE}/{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def make_pass(min_interval=timedelta(minutes=15)):
    """Post-race pass bound to Strapi and the MotoGP API, for the runner. Returns pass(now) ->
    (pending: bool, problems: list). Looks at Grand Prix whose Sprint or Race started in the last 30 h."""
    from cron.strapi_api.apis import get_races_starting_between, get_race_results_for_grand_prix, \
        update_race_result, update_config_for_race_result
    from cron.stats_calc.moto_gp.moto_gp_stats_update import process_update_moto_gp_stats
    import json

    def iso(dt):
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def write(row_id, fields):
        update_race_result(is_f1_feed=False, json_str=json.dumps(fields), row_id=row_id)

    def run(now: datetime):
        races = get_races_starting_between(False, iso(now - timedelta(hours=30)), iso(now))
        gps = {}
        for r in races:
            t = r["attributes"]["type"]
            if t not in ("Sprint", "Race"):
                continue
            g = r["attributes"]["grandPrix"]["data"]
            a = g["attributes"]
            started = datetime.fromisoformat(r["attributes"]["startTime"].replace("Z", "+00:00"))
            gps.setdefault(g["id"], {"gp": {"id": g["id"], "shortName": a["shortName"],
                                            "year": a["season"]["data"]["attributes"]["year"]}, "started": {}})
            gps[g["id"]]["started"][t] = started
        pending, problems = False, []
        for gp_id, item in gps.items():
            st = _state.get(gp_id)
            if st and now - st["last"] < min_interval:
                pending = pending or st["pending"]  # between checks, report what the last check found
                continue
            try:
                changed, p, probs = run_gp(item["gp"], item["started"], now, pulselive,
                                           lambda gid: get_race_results_for_grand_prix(False, gid, ["QNR1", "QNR2", "Sprint"]),
                                           write)
            except Exception as e:
                logger.exception(f"post-race pass failed for GP {gp_id}")
                problems.append(f"post-race GP {gp_id}: {type(e).__name__}: {e}")
                _state[gp_id] = {"last": now, "pending": True}
                pending = True
                continue
            _state[gp_id] = {"last": now, "pending": bool(p)}
            if p:
                logger.info(f"post-race pending: {p}")
                pending = True
            problems += probs
            if changed:
                process_update_moto_gp_stats(season_year=str(item["gp"]["year"]))
                update_config_for_race_result(is_f1_feed=False, gp_id=gp_id)
        return pending, problems

    return run
