"""MotoGP weekend results runner (used by .github/workflows/race-result.yml).

GitHub starts scheduled workflows in this repo only about every 4 hours, whatever the cron says
(measured on the Qatar 2026 weekend: 18 scheduled runs instead of 576). A one-shot ingest therefore
reaches the app hours late. This runner stays alive instead: it ingests every session as soon as its
classification is published (polling, like the results watcher), and near the 6 hour job limit it asks
the workflow to start a new run while a session is still waiting or about to start. Away from race
weekends it exits at once.

Environment: RUNNER_MAX_MINUTES (default 330), RUNNER_POLL_SECONDS (default 120),
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
POLL_SECONDS = int(os.getenv("RUNNER_POLL_SECONDS", "120"))
# Keep the chain alive when the next session starts within this many hours. Covers the longest gap
# inside a weekend (Saturday Sprint to Sunday Race, about 22 h), not the gap between weekends.
CHAIN_LOOKAHEAD_HOURS = int(os.getenv("RUNNER_LOOKAHEAD_HOURS", "26"))
# Never chain a run that ended this quickly: a broken run must not re-dispatch itself in a tight loop.
MIN_MINUTES_BEFORE_CHAIN = 20


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def next_session_start(now: datetime):
    """Next moment the runner must be awake: a session start or a reminder time (start minus 15 min)."""
    races = get_races_starting_between(False, iso(now), iso(now + timedelta(hours=CHAIN_LOOKAHEAD_HOURS)))
    events = []
    for r in races:
        start = uploader.parse_time(r["attributes"]["startTime"])
        events.append(start)
        if reminders.wants_reminder(r):
            events.append(start - reminders.LEAD)
    events = [e for e in events if e > now]
    return min(events) if events else None


def _send_reminder(messages):
    from cron.notifiaction.notification_utils import send_localized_notification_to_topic
    send_localized_notification_to_topic(is_f1=False, is_prod=True, messages=messages)


def make_reminder_pass():
    """Reminder pass bound to the real Strapi, GitHub record and Firebase sender."""
    store = reminders.SentStore()
    enabled = os.getenv("MOTOZ_SESSION_PUSH", "").strip().lower() == "on"
    logger.info(f"session reminders {'ON' if enabled else 'dry run (MOTOZ_SESSION_PUSH is not on)'}")
    logged = set()
    fetch = lambda start, end: get_races_starting_between(False, iso(start), iso(end))
    return lambda now: reminders.run_pass(now, fetch, store, _send_reminder, enabled, logged)


def next_wake(now: datetime, waiting: bool, next_start, deadline: datetime, poll: timedelta):
    """When to run the next ingest pass, or None when nothing can happen before the deadline."""
    if waiting:
        wake = now + poll
        if next_start is not None and now < next_start < wake:
            wake = next_start  # a reminder or session start falls inside the poll interval: be on time
    elif next_start is not None:
        wake = max(next_start, now + poll)
    else:
        return None
    return wake if wake < deadline else None


def should_chain(waiting: bool, next_start, now: datetime, started_at: datetime) -> bool:
    if (now - started_at) < timedelta(minutes=MIN_MINUTES_BEFORE_CHAIN):
        return False
    upcoming = next_start is not None and next_start - now <= timedelta(hours=CHAIN_LOOKAHEAD_HOURS)
    return waiting or upcoming


def run(clock=lambda: datetime.now(timezone.utc), sleep=time.sleep, process=uploader.process,
        next_start_fn=next_session_start, max_minutes=MAX_MINUTES, poll_seconds=POLL_SECONDS,
        remind=lambda now: []):
    started_at = clock()
    deadline = started_at + timedelta(minutes=max_minutes)
    poll = timedelta(seconds=poll_seconds)
    problems = []
    waiting, next_start = False, None

    while True:
        now = clock()
        try:
            problems += remind(now)
        except Exception as e:
            logger.exception(f"reminder pass failed: {type(e).__name__}: {e}")
            problems.append(f"reminder pass: {type(e).__name__}: {e}")
        try:
            summary = process(now=now)
            problems += summary["skipped_missing_grid"] + summary["errors"]
            waiting = bool(summary["waiting"])
        except Exception as e:  # Strapi or API down: keep the weekend alive and retry
            logger.exception(f"ingest pass failed: {type(e).__name__}: {e}")
            problems.append(f"ingest pass: {type(e).__name__}: {e}")
            waiting = True
        try:
            next_start = next_start_fn(now)
        except Exception as e:
            logger.exception(f"schedule lookup failed: {type(e).__name__}: {e}")
            waiting = True

        now = clock()
        if next_start is None and not waiting:
            logger.info("no session waiting and none in the next hours: weekend done")
            return False, problems
        wake = next_wake(now, waiting, next_start, deadline, poll)
        if wake is None:
            # Nothing more can happen in this job. Idle to the deadline, then hand over to a new run.
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
    chain, problems = run(remind=make_reminder_pass())
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
