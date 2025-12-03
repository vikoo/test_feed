# test_feed

to run internal scripts
1. go to root directory and run command
   ```bash
   export PYTHONPATH=.
2. stay on root directory and run the command by giving full path to run the script. 
3. This will fetch the feeds 
   ```bash
   python cron/rss/rss.py
   
4. This will clean old feeds and votes
   ```bash
   python cron/rss/clean_rss.py
   
5. This will fetch the weather for the grand prix 
   ```bash
   python cron/weather/weather.py