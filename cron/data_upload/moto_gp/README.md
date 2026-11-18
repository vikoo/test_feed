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
