"""MotoGP weekend results runner (used by .github/workflows/race-result.yml).

GitHub starts scheduled workflows in this repo only about every 4 hours, whatever the cron says
(measured on the Qatar 2026 weekend: 18 scheduled runs instead of 576). A one-shot ingest therefore
reaches the app hours late. This runner stays alive instead: it ingests every session as soon as its
classification is published (polling, like the results watcher), and near the 6 hour job limit it asks
the workflow to start a new run while a session is still waiting or about to start. Away from race
weekends it exits at once.

Environment: RUNNER_MAX_MINUTES (default 330), RUNNER_POLL_SECONDS (default 60),
RUNNER_LOOKAHEAD_HOURS (default 26).
Writes chain=true|false to $GITHUB_OUTPUT. Exit code 1 if any session failed or was skipped.
"""
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from cron.data_upload.moto_gp import moto_gp_data_upload as uploader
from cron.notifiaction import moto_gp_session_reminders as reminders
from cron.strapi_api.apis import get_races_starting_between

MAX_MINUTES = int(os.getenv("RUNNER_MAX_MINUTES", "330"))
# Poll interval while a session is waiting for its classification or its results push: results reach the
# app at most this long after motogp.com publishes them.
POLL_SECONDS = int(os.getenv("RUNNER_POLL_SECONDS", "60"))
# Keep the chain alive when the next session starts within this many hours. Covers the longest gap
# inside a weekend (Saturday Sprint to Sunday Race, about 22 h), not the gap between weekends.
CHAIN_LOOKAHEAD_HOURS = int(os.getenv("RUNNER_LOOKAHEAD_HOURS", "26"))
# Never chain a run that ended this quickly: a broken run must not re-dispatch itself in a tight loop.
MIN_MINUTES_BEFORE_CHAIN = 20
# Stop handing over when nothing has worked for this long (revoked token, long outage), so a broken
# setup does not chain runs forever; the next scheduled kick-off tries again.
MAX_HOURS_WITHOUT_SUCCESS = 6
# Never sleep longer than this between passes: a session moved earlier in the official timetable (or
# cancelled) is seen within this time, so its reminder is not missed.
MAX_IDLE = timedelta(minutes=10)
# Stop starting passes this long before the job limit and hand over at once: a slow last pass cannot
# hit the workflow timeout (which would skip the hand-over), and the next run is up before the limit.
HANDOVER_MARGIN = timedelta(minutes=15)
# Hand over at a quiet moment: in the last HANDOVER_WINDOW of a job, hand over as soon as no reminder is due
# within QUIET_GAP. The next run then has QUIET_GAP + 15 min (the reminder lead) to start, so a slow GitHub
# start (queue, checkout, pip, apt) cannot make a push late or lose it. Reminders are at least 40 min apart,
# so such a moment always comes (at the latest right after a reminder is sent).
HANDOVER_WINDOW = timedelta(minutes=75)
QUIET_GAP = timedelta(minutes=35)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


_upcoming_cache = {}


def upcoming(now: datetime):
    """(session starts after now, reminder times after now, reminder times of sessions not started yet).
    The last list keeps a reminder whose time has just passed: it may not have been sent yet."""
    if _upcoming_cache.get("now") == now:
        return _upcoming_cache["value"]
    # From 3 h back: a session whose official time is earlier than Strapi's must still be seen.
    races = get_races_starting_between(False, iso(now - timedelta(hours=3)), iso(now + timedelta(hours=CHAIN_LOOKAHEAD_HOURS)))
    starts, reminds, open_reminds = [], [], []
    for r in races:
        starts.append(uploader.parse_time(r["attributes"]["startTime"]))
        if reminders.wants_reminder(r):
            eff = reminders.effective_start(r, now)  # official time wins
            reminds.append(eff - reminders.LEAD)
            if eff > now:
                open_reminds.append(eff - reminders.LEAD)
            reminders.official_status(r, now)  # keep the cancelled status cached before the reminder is due
    value = ([e for e in starts if e > now], [e for e in reminds if e > now], open_reminds)
    _upcoming_cache.update(now=now, value=value)
    return value


def next_session_start(now: datetime):
    """Next moment the runner must be awake: a session start or a reminder time (start minus 15 min)."""
    starts, reminds, _ = upcoming(now)
    return min(starts + reminds) if starts or reminds else None


def next_reminder(now: datetime):
    """Earliest reminder time after `now`. The runner asks with the time its reminder pass ran, so a reminder
    whose time fell during the pass (not sent yet) still counts as ahead."""
    _, reminds, _ = upcoming(now)
    return min(reminds) if reminds else None


def _send_reminder(messages):
    from cron.notifiaction.notification_utils import send_localized_notification_to_topic
    send_localized_notification_to_topic(is_f1=False, is_prod=True, messages=messages)


def push_enabled() -> bool:
    return os.getenv("MOTOZ_SESSION_PUSH", "").strip().lower() == "on"


def make_reminder_pass(store=None):
    """Reminder pass bound to the real Strapi, GitHub record and Firebase sender."""
    store = store or reminders.SentStore()
    enabled = push_enabled()
    logger.info(f"session reminders {'ON' if enabled else 'dry run (MOTOZ_SESSION_PUSH is not on)'}")
    logged = set()
    fetch = lambda start, end: get_races_starting_between(False, iso(start), iso(end))
    return lambda now: reminders.run_pass(now, fetch, store, _send_reminder, enabled, logged)


def next_wake(now: datetime, waiting: bool, next_start, deadline: datetime, poll: timedelta):
    """When to run the next ingest pass, or None when nothing can happen before the deadline."""
    if next_start is not None and next_start <= now:
        wake = now  # the event fell during the pass just finished (passes take seconds): run again at once
    elif waiting:
        wake = now + poll
        if next_start is not None and now < next_start < wake:
            wake = next_start  # a reminder or session start falls inside the poll interval: be on time
    elif next_start is not None:
        wake = min(next_start, now + max(MAX_IDLE, poll))
    else:
        return None
    return wake if wake < deadline else None


def should_chain(waiting: bool, next_start, now: datetime, started_at: datetime) -> bool:
    if (now - started_at) < timedelta(minutes=MIN_MINUTES_BEFORE_CHAIN):
        return False
    upcoming = next_start is not None and next_start - now <= timedelta(hours=CHAIN_LOOKAHEAD_HOURS)
    return waiting or upcoming


def make_followup_pass(store):
    """Results follow-up (sync with motogp.com, results push, stats) bound to the real services."""
    from cron.data_upload.moto_gp import results_followup
    enabled = push_enabled()
    logger.info(f"results push {'ON' if enabled else 'dry run (MOTOZ_SESSION_PUSH is not on)'}")
    f = results_followup.Followup(results_followup.LiveDeps(), store, enabled)
    uploader.defer_stats = True

    def run_pass(now):
        owed = set(uploader.stats_owed)
        uploader.stats_owed.clear()
        f.bump_owed |= uploader.bump_owed
        uploader.bump_owed.clear()
        return f.run(now, stats_owed=owed)  # f keeps both until they work
    return run_pass


def run(clock=lambda: datetime.now(timezone.utc), sleep=time.sleep, process=uploader.process,
        next_start_fn=next_session_start, max_minutes=MAX_MINUTES, poll_seconds=POLL_SECONDS,
        remind=lambda now: [], post_race=lambda now: (False, []), time_sync=lambda now: [], next_reminder_fn=None,
        followup=lambda now: (False, [])):
    # Without a reminder lookup (tests), every upcoming event is treated as a reminder: the safe side.
    next_reminder_fn = next_reminder_fn or next_start_fn
    started_at = clock()
    deadline = started_at + timedelta(minutes=max_minutes)
    last_pass_by = deadline - HANDOVER_MARGIN if max_minutes * 60 > 2 * HANDOVER_MARGIN.total_seconds() else deadline
    _upcoming_cache.clear()
    poll = timedelta(seconds=poll_seconds)
    problems = []
    waiting, next_start = False, None
    last_ok = started_at

    while True:
        now = clock()
        pass_at = now  # when the reminder pass below looks at the clock
        ok = True
        try:
            problems += time_sync(now)  # upcoming session times = official timetable (throttled to hourly)
        except Exception as e:
            logger.exception(f"session time check failed: {type(e).__name__}: {e}")
            problems.append(f"session time check: {type(e).__name__}: {e}")
        remind_failed = False
        try:
            remind_problems = remind(now)
            problems += remind_problems
            remind_failed = bool(remind_problems)  # a failed send or record: retry every poll until the start
        except Exception as e:
            logger.exception(f"reminder pass failed: {type(e).__name__}: {e}")
            problems.append(f"reminder pass: {type(e).__name__}: {e}")
            remind_failed = True
        try:
            summary = process(now=now)
            problems += summary["skipped_missing_grid"] + summary["errors"]
            waiting = bool(summary["waiting"])
        except Exception as e:  # Strapi or API down: keep the weekend alive and retry
            logger.exception(f"ingest pass failed: {type(e).__name__}: {e}")
            problems.append(f"ingest pass: {type(e).__name__}: {e}")
            waiting, ok = True, False
        try:
            follow_pending, follow_problems = followup(now)  # keep the app equal to motogp.com, results push
            problems += follow_problems
            waiting = waiting or follow_pending
        except Exception as e:
            logger.exception(f"results follow-up failed: {type(e).__name__}: {e}")
            problems.append(f"results follow-up: {type(e).__name__}: {e}")
            waiting = True
        try:
            post_pending, post_problems = post_race(now)
            problems += post_problems
            waiting = waiting or post_pending  # keep polling until the official PDFs are in
        except Exception as e:
            logger.exception(f"post-race pass failed: {type(e).__name__}: {e}")
            problems.append(f"post-race pass: {type(e).__name__}: {e}")
        waiting = waiting or remind_failed
        try:
            next_start = next_start_fn(now)
        except Exception as e:
            logger.exception(f"schedule lookup failed: {type(e).__name__}: {e}")
            next_start = None  # a stale past value would make every pass run back to back
            waiting, ok = True, False

        now = clock()
        if ok:
            last_ok = now
        elif now - last_ok > timedelta(hours=MAX_HOURS_WITHOUT_SUCCESS):
            logger.error(f"nothing has worked for {MAX_HOURS_WITHOUT_SUCCESS} h: stopping without handing over")
            return False, problems
        if next_start is None and not waiting:
            logger.info("no session waiting and none in the next hours: weekend done")
            return False, problems
        # The handover follows reminders only. Delaying it while a session waits for results was tried and lost a
        # reminder with a 20 min GitHub start (WaitingHandoverTest); the results follow-up keeps no state in
        # memory, so a handover only pauses the results while the next run starts.
        if now >= deadline - HANDOVER_WINDOW and should_chain(waiting, next_start, now, started_at):
            try:
                nr = next_reminder_fn(pass_at)  # reminders after the reminder pass are still to send
            except Exception:
                nr = None if next_start is None else next_start
            if nr is None or nr - now >= QUIET_GAP:
                logger.info(f"handing over at a quiet moment (next reminder {nr})")
                return True, problems
        wake = next_wake(now, waiting, next_start, last_pass_by, poll)
        if wake is None:
            # Nothing more can happen in this job: hand over to a new run now, while there is time.
            if should_chain(waiting, next_start, now, started_at):
                logger.info(f"job time nearly used up, handing over (next session {next_start})")
                return True, problems
            if deadline > now:
                logger.info(f"next session {next_start}, idling until {deadline} then chaining")
                sleep((deadline - now).total_seconds())
            chain = should_chain(waiting, next_start, clock(), started_at)
            logger.info(f"job time used up, chain={chain}")
            return chain, problems
        logger.info(f"waiting={waiting} next_start={next_start}, next pass at {wake}")
        sleep(max(0.0, (wake - now).total_seconds()))


def main():
    socket.setdefaulttimeout(90)  # the Strapi helpers send requests without a timeout; never hang a 6 h job
    started = datetime.now(timezone.utc)
    try:
        from cron.data_upload.moto_gp import post_race, time_sync, auto_grid
        uploader.on_missing_grid = auto_grid.make_handler()  # new substitute / wild card: create the grid
        store = reminders.SentStore()  # one record for reminders and results pushes (one writer, one sha)
        chain, problems = run(remind=make_reminder_pass(store), post_race=post_race.make_pass(),
                              time_sync=time_sync.make_pass(), next_reminder_fn=next_reminder,
                              followup=make_followup_pass(store))
    except Exception as e:
        # Unexpected crash: hand over only if this run lasted long enough (never a tight re-dispatch loop).
        logger.exception(f"runner crashed: {type(e).__name__}: {e}")
        chain = datetime.now(timezone.utc) - started >= timedelta(minutes=MIN_MINUTES_BEFORE_CHAIN)
        problems = [f"runner crashed: {type(e).__name__}: {e}"]
    problems = list(dict.fromkeys(problems))  # a skipped session is retried, and reported, on every pass
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"chain={'true' if chain else 'false'}\n")
    if problems:
        logger.error(f"problems this run: {problems}")
        sys.exit(1)


if __name__ == "__main__":
    main()
