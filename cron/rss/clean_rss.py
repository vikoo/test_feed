from cron.strapi_api.apis import *
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

def fetch_and_clean_feeds(is_f1_feed: bool, lang: str = "en"):
  # Cutoff: 20 days ago
  cutoff_date = datetime.now(timezone.utc) - timedelta(days=10)

  # Format as "YYYY-MM-DDTHH:MM:SS.sssZ"
  cutoff_date_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

  start = 0
  limit = 50
  total_deleted = 0

  while True:
    feeds = fetch_old_feeds(is_f1_feed, cutoff_date_str, start=start, limit=limit, lang= lang)
    if not feeds:
      break

    for feed in feeds:
      fid = feed["id"]
      print(f"Deleting feed {fid} ...")
      delete_feed(is_f1_feed, fid)
      total_deleted += 1

    start += limit

  print(f"✅ Finished cleanup. Deleted {total_deleted} old feeds for locale {lang}")


def fetch_and_clean_votes(is_f1_feed: bool):
  # Cutoff: 20 days ago
  cutoff_date = datetime.now(timezone.utc) - timedelta(days=10)

  # Format as "YYYY-MM-DDTHH:MM:SS.sssZ"
  cutoff_date_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

  start = 0
  limit = 50
  total_deleted = 0

  while True:
    votes = fetch_old_votes(is_f1_feed, cutoff_date_str, start=start, limit=limit)
    if not votes:
      break

    for vote in votes:
      fid = vote["id"]
      print(f"Deleting vote {fid} ...")
      delete_vote(is_f1_feed, fid)
      total_deleted += 1

    start += limit

  print(f"✅ Finished cleanup. Deleted {total_deleted} old votes.")


def fetch_and_clean_vote_counts(is_f1_feed: bool):
  # Cutoff: 20 days ago
  cutoff_date = datetime.now(timezone.utc) - timedelta(days=10)

  # Format as "YYYY-MM-DDTHH:MM:SS.sssZ"
  cutoff_date_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

  start = 0
  limit = 50
  total_deleted = 0

  while True:
    votes = fetch_old_vote_counts(is_f1_feed, cutoff_date_str, start=start, limit=limit)
    if not votes:
      break

    for vote in votes:
      fid = vote["id"]
      print(f"Deleting vote count {fid} ...")
      delete_vote_count(is_f1_feed, fid)
      total_deleted += 1

    start += limit

  print(f"✅ Finished cleanup. Deleted {total_deleted} old votes.")


if __name__ == "__main__":
  print(f"------------- FETCHING F1 FEEDS ------------------")
  locales_updated = locales
  locales_updated.add("en")
  for locale in locales_updated:
    fetch_and_clean_feeds(True, lang= locale)
  print(f"------------- FETCHING MOTO GP FEEDS ------------------")
  for locale in locales_updated:
    fetch_and_clean_feeds(False, lang= locale)
  print(f"------------- Cleaning Votes ------------------")
  print(f"------------- FETCHING F1 votes ------------------")
  fetch_and_clean_votes(True)
  fetch_and_clean_vote_counts(True)
  print(f"------------- FETCHING MOTO GP votes ------------------")
  fetch_and_clean_votes(False)
  fetch_and_clean_vote_counts(False)
