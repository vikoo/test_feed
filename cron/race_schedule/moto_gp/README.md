# schedule fetch for wheelie

Please make sure all the Tracks are available in db. It will work even if track is not available.
to run script
1. go to root directory and run command
   ```bash
   export PYTHONPATH=.
   
2. stay on root directory and run the command by giving full path to run the script
      You can pass --year argument to fetch the schedule for the given year. if argument is not passed it will take current year,
      ```bash
      python cron/race_schedule/moto_gp_schedule_upload.py --year 2024
   
This will take current year 

   ```bash 
   python cron/race_schedule/moto_gp_schedule_upload.py