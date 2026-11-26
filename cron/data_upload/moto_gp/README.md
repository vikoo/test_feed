# schedule fetch for wheelie

Please make sure all the Tracks are available in db. It will work even if track is not available.
to run script
1. go to root directory and run command
   ```bash
   export PYTHONPATH=.
   
2. stay on root directory and run the command by giving full path to run the script

      ```bash
      python cron/data_upload/moto_gp/moto_gp_data_upload.py
   

## Weekend runner (race-result.yml)

GitHub starts scheduled runs of this repo only about every 4 hours, so `weekend_runner.py` does not rely
on the cron cadence. A run polls every minute, ingests each session as soon as its classification is
published (never earlier than the minimum session length after the start), and before the 6 hour job
limit starts a new run of the workflow while a session is waiting or the next one starts within 26 hours.
While idle it still wakes at least every 10 minutes, so a session moved earlier is seen in time. The
hand-over happens at a quiet moment (no reminder due within 35 minutes, in the last 75 minutes of a job),
so a new run that takes up to 50 minutes to start cannot make a reminder late or lose it.
A Sprint or Race is written only once every rider in a scoring position (top 9 / top 15) has points:
motogp.com often shows the order first and the points a little later; the runner keeps polling every
minute and writes the result as soon as the points are in. Away from race weekends it exits within a minute. Manual runs are not needed during a weekend; the
`once` mode keeps the old single pass.

After the write, `results_followup.py` runs on every pass for each session of the last 6 hours (nothing
important is kept in memory, so a handover changes nothing):
- **Sync.** The session's Strapi rows (read uncached) are compared with motogp.com's current classification
  and every difference is rewritten: practice and qualifying position, time, laps, dnf and Q1 finalPos;
  Sprint and Race time and laps plus the Race fastest lap (order, points and dnf stay with the PDF-checked
  corrections below). Missing rows (a write that failed halfway) are created. motogp.com publishes a
  provisional classification first (`"official": false`, times rounded to 0.01 s) and the official one
  minutes later; a provisional copy coarser than what the app already shows (a stale CDN copy) is ignored.
- **Results push**, once per session, recorded on `motogp-state` next to the reminders (`results:<race id>`
  and `results:<event>:<type>`), so it is never sent twice and a failed or held push is retried on the next
  pass. It goes when the app shows exactly motogp.com's classification and at least 6 minutes after the last
  row change (the Strapi proxy caches identical GraphQL queries, the app's too, for about 5 minutes): Practice
  and Q2 once the classification is official, or 10 minutes after the first write if it is still
  provisional; FP1, FP2, Sprint and Race without waiting for it. The results cache key is bumped right before the send. No push after
  Q1, none 30 minutes after the first write or 24 h after the start. Paused like the reminders
  (`MOTOZ_SESSION_PUSH`, `control.json`).
- **Stats** are recomputed after the push for every season written in the pass.

Typical timing (Portugal FP1 2026 replay): official about 7 min after the first write, push 6 min later.

A rider with no season grid no longer aborts the run halfway: the session is skipped with nothing
written, the other sessions still run, and the job ends red so the failure email goes out. Riders whose
only grid is marked `isOldGrid` (substitutes after their weekend) use that grid.

## Session reminder pushes

The runner also sends the reminder push about 15 minutes before FP1, Practice, FP2, Q1, Sprint and Race
(no Q2, no Warm Up, nothing for a cancelled Grand Prix), with hand-written copy per language
(`cron/notifiaction/moto_gp_session_reminders.py`). It sends only when the repository variable
`MOTOZ_SESSION_PUSH` is `on`; otherwise it logs "would send". Reminded sessions are recorded in
`session_reminders_sent.json` on the `motogp-state` branch, by Strapi race id and by official event and
session, so a session is never reminded twice (not even when Strapi holds a duplicated race row). Never
more than one reminder per pass: two different sessions due at once means bad data, nothing is sent.
The results push uses fixed, hand-written copy per session and language (`RESULT_TEMPLATES` in the same file, no machine translation) and is not sent after Q1. It goes out
only once the app can read the results: the rows of the session and the results cache key are read back
from Strapi first (held and reported otherwise). A session written more than 24 hours after its start (a
grid fixed days later, a manual rerun) is not announced.

## Operating the reminders during a weekend

- Off for good: set the repository variable `MOTOZ_SESSION_PUSH` to anything other than `on`. A run already in
  progress keeps the value it started with, so also use the control file below.
- Pause now, or skip one session (for example one that was cancelled): edit `control.json` on the
  `motogp-state` branch (GitHub web editor is fine). It is read before every send.
  - `{"session_push": "off"}` pauses every reminder; `{"session_push": "on"}` or no file resumes.
  - `{"skip_race_ids": ["606"]}` skips the session with Strapi race id 606 (`"606"` or `606` work too).
- Reminders follow the official motogp.com timetable, read again right before every push: a session moved
  at the last moment is reminded at its new time, one cancelled at the last moment is not reminded.
- Reminders follow the official motogp.com timetable. A same-day difference with Strapi (what the app
  shows) is logged as a warning; differences more than 6 hours ahead are fixed by the time check below.

## Post-race checks (post_race.py)

After each Sprint and Race the runner, every 15 minutes until done:
- sets the official starting grid from the FIM Grid PDF (finalPos / sprintFinalPos on the qualifying rows),
- sets the Sprint fastest lap from the Sprint Classification PDF when it is missing,
- compares every rider's stored points with the official classification and ends the run red on any
  difference that the corrections below cannot settle (the API and the PDF disagree).
It then reruns the stats and bumps the results cache of that Grand Prix. A missing PDF is retried for
8 hours after the session start, then reported.

## More automation (corrections.py, time_sync.py, auto_grid.py)

- Result corrections, every finished session (FP1 to Race), every 15 minutes during the weekend: times and
  laps from the API (cross-checked with the FIM PDF for Sprint and Race), Sprint/Race order including
  non-classified riders from the PDF, dnf, and points after penalties when the API and the PDF agree.
  Disagreements are reported, not written.
- Standings check after each Sprint and Race: riders, teams and constructors against the official tables
  (alarm only).
- Session times: every run (hourly, every day) sets upcoming session times (next 8 days) to the official
  timetable when they differ by 5+ minutes and both are more than 6 hours away (same-day delays are kept as
  planned). GP window kept consistent; calendar cache bumped.
- Reminders skip a session the official timetable marks CANCELLED.
- New substitute or wild card: the season grid is created (team-mate's bike and colour, default photo) and,
  for a substitute, linked to the team; the session is then ingested. The run ends red with what was done:
  add the photo and check the decision.
- Rider of a new team (nobody of that team in Strapi): grid with the same make's factory bike and colour, no
  team link, session ingested; alarm to create the team, chassis and team standing. A new manufacturer (no
  bike of that make) or two rider records with the same name: nothing created, alarm, session waits.
- A number that already has a current grid never gets a second one. Every created grid bumps the
  `driverTeamTrackSeasonTyre` and `chassisSeasonGrid` caches.
- Failures stay contained: each pass (times, reminders, ingest, post-race) and each session, Grand Prix and
  rider is handled on its own, so one failure is reported and the rest carries on. A correction written
  but not followed by the stats and cache update is retried until that update succeeds. A session with no
  classification 8 hours after its start is reported once. Nothing here writes to `main` or triggers
  another workflow.
