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
on the cron cadence. A run polls every 2 minutes, ingests each session as soon as its classification is
published (never earlier than the minimum session length after the start), and before the 6 hour job
limit starts a new run of the workflow while a session is waiting or the next one starts within 26 hours.
Away from race weekends it exits within a minute. Manual runs are not needed during a weekend; the
`once` mode keeps the old single pass.

A rider with no season grid no longer aborts the run halfway: the session is skipped with nothing
written, the other sessions still run, and the job ends red so the failure email goes out. Riders whose
only grid is marked `isOldGrid` (substitutes after their weekend) use that grid.

## Session reminder pushes

The runner also sends the reminder push about 15 minutes before FP1, Practice, FP2, Q1, Sprint and Race
(no Q2, no Warm Up, nothing for a cancelled Grand Prix), with hand-written copy per language
(`cron/notifiaction/moto_gp_session_reminders.py`). It sends only when the repository variable
`MOTOZ_SESSION_PUSH` is `on`; otherwise it logs "would send". Reminded sessions are recorded in
`session_reminders_sent.json` on the `motogp-state` branch, so a session is never reminded twice.
The results push now names sessions plainly (Practice, Qualifying) and is not sent after Q1.

## Operating the reminders during a weekend

- Off for good: set the repository variable `MOTOZ_SESSION_PUSH` to anything other than `on`. A run already in
  progress keeps the value it started with, so also use the control file below.
- Pause now, or skip one session (for example one that was cancelled): edit `control.json` on the
  `motogp-state` branch (GitHub web editor is fine). It is read before every send.
  - `{"session_push": "off"}` pauses every reminder; `{"session_push": "on"}` or no file resumes.
  - `{"skip_race_ids": ["606"]}` skips the session with Strapi race id 606.
- Reminders follow the official motogp.com timetable. When the Strapi time (what the app shows) differs by
  5 minutes or more, the reminder still goes at the official time and the run ends red with the session
  named, so the app time can be fixed.

## Post-race checks (post_race.py)

After each Sprint and Race the runner, every 15 minutes until done:
- sets the official starting grid from the FIM Grid PDF (finalPos / sprintFinalPos on the qualifying rows),
- sets the Sprint fastest lap from the Sprint Classification PDF when it is missing,
- compares every rider's stored points with the official classification and ends the run red on any
  difference (late penalty, missing points, wrong red-flag part). It does not rewrite results.
It then reruns the stats and bumps the results cache of that Grand Prix. A missing PDF is retried for
8 hours after the session start, then reported.
