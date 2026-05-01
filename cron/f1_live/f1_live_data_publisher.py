"""
F1 Live Data Publisher

Continuously scrapes F1 live timing data and publishes it to AWS IoT Core MQTT broker
every 2 minutes.

Usage:
    python f1_live_data_publisher.py
"""

import json
import time
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from f1_live_data import scrape_f1_live_table
from mqtt.ps_mqtt import build_client, publish, F1_LIVE_DATA_TOPIC

# Configuration
PUBLISH_INTERVAL = 5  # seconds (60 for production, 10 for testing)
USE_FALLBACK_DATA = False  # Set to True to send fallback data when no live data is available, False to skip publish

# Persistent MQTT client (reused for all publishes)
mqtt_client = None

# Fallback data to send in case of errors
FALLBACK_F1_DATA = [
  {
    "Pos": "1",
    "First Name": "George",
    "Last Name": "Russell",
    "Team": "Mercedes",
    "Abbreviation": "RUS",
    "Gap": "1:33.030",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "2",
    "First Name": "Lewis",
    "Last Name": "Hamilton",
    "Team": "Ferrari",
    "Abbreviation": "HAM",
    "Gap": "+0.118",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "3",
    "First Name": "Charles",
    "Last Name": "Leclerc",
    "Team": "Ferrari",
    "Abbreviation": "LEC",
    "Gap": "+0.164",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "4",
    "First Name": "Kimi",
    "Last Name": "Antonelli",
    "Team": "Mercedes",
    "Abbreviation": "ANT",
    "Gap": "+0.425",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "5",
    "First Name": "Lando",
    "Last Name": "Norris",
    "Team": "McLaren",
    "Abbreviation": "NOR",
    "Gap": "+0.753",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "6",
    "First Name": "Oscar",
    "Last Name": "Piastri",
    "Team": "McLaren",
    "Abbreviation": "PIA",
    "Gap": "+0.783",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "7",
    "First Name": "Pierre",
    "Last Name": "Gasly",
    "Team": "Alpine",
    "Abbreviation": "GAS",
    "Gap": "+0.940",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "8",
    "First Name": "Nico",
    "Last Name": "Hulkenberg",
    "Team": "Audi",
    "Abbreviation": "HUL",
    "Gap": "+0.967",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "9",
    "First Name": "Esteban",
    "Last Name": "Ocon",
    "Team": "Haas F1 Team",
    "Abbreviation": "OCO",
    "Gap": "+1.057",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "10",
    "First Name": "Liam",
    "Last Name": "Lawson",
    "Team": "Racing Bulls",
    "Abbreviation": "LAW",
    "Gap": "+1.080",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "11",
    "First Name": "Max",
    "Last Name": "Verstappen",
    "Team": "Red Bull Racing",
    "Abbreviation": "VER",
    "Gap": "+1.140",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "12",
    "First Name": "Oliver",
    "Last Name": "Bearman",
    "Team": "Haas F1 Team",
    "Abbreviation": "BEA",
    "Gap": "+1.250",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "13",
    "First Name": "Gabriel",
    "Last Name": "Bortoleto",
    "Team": "Audi",
    "Abbreviation": "BOR",
    "Gap": "+1.261",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "14",
    "First Name": "Isack",
    "Last Name": "Hadjar",
    "Team": "Red Bull Racing",
    "Abbreviation": "HAD",
    "Gap": "+1.417",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "15",
    "First Name": "Arvid",
    "Last Name": "Lindblad",
    "Team": "Racing Bulls",
    "Abbreviation": "LIN",
    "Gap": "+1.465",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "16",
    "First Name": "Franco",
    "Last Name": "Colapinto",
    "Team": "Alpine",
    "Abbreviation": "COL",
    "Gap": "+1.562",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "17",
    "First Name": "Carlos",
    "Last Name": "Sainz",
    "Team": "Williams",
    "Abbreviation": "SAI",
    "Gap": "+1.731",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "18",
    "First Name": "Alexander",
    "Last Name": "Albon",
    "Team": "Williams",
    "Abbreviation": "ALB",
    "Gap": "+2.275",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "19",
    "First Name": "Fernando",
    "Last Name": "Alonso",
    "Team": "Aston Martin",
    "Abbreviation": "ALO",
    "Gap": "+2.551",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "20",
    "First Name": "Lance",
    "Last Name": "Stroll",
    "Team": "Aston Martin",
    "Abbreviation": "STR",
    "Gap": "+3.121",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "21",
    "First Name": "Valtteri",
    "Last Name": "Bottas",
    "Team": "Cadillac",
    "Abbreviation": "BOT",
    "Gap": "+4.348",
    "Tyre": "Medium",
    "Tyres Used": "1"
  },
  {
    "Pos": "22",
    "First Name": "Sergio",
    "Last Name": "Perez",
    "Team": "Cadillac",
    "Abbreviation": "PER",
    "Gap": "- -",
    "Tyre": "Empty",
    "Tyres Used": "0"
  }
]


def publish_f1_live_data(client) -> bool:
    """
    Scrape F1 live timing data and publish to MQTT using persistent client.
    If scraping fails and USE_FALLBACK_DATA is True, publishes fallback sample data instead.
    If USE_FALLBACK_DATA is False, skips publish on error.

    Args:
        client: Persistent MQTT client to use for publishing

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("🏎️  Scraping F1 live timing data...")
        json_str = scrape_f1_live_table()
        records = json.loads(json_str)

        if not records:
            if USE_FALLBACK_DATA:
                logger.warning("⚠️  No F1 data scraped. Using fallback sample data...")
                records = FALLBACK_F1_DATA
            else:
                logger.warning("⚠️  No F1 data scraped. Skipping publish (USE_FALLBACK_DATA=False)")
                return False

        logger.info(f"✅ Prepared {len(records)} driver records")

        # Publish to MQTT (with retention enabled by default)
        logger.info(f"📡 Publishing to topic: {F1_LIVE_DATA_TOPIC}")
        publish(
            payload=records,
            topic=F1_LIVE_DATA_TOPIC,
            qos=1,
            client=client,
            retain=False
        )

        logger.info(f"✅ Successfully published {len(records)} records to AWS IoT Core")
        return True

    except Exception as e:
        logger.error(f"❌ Error during scrape/publish cycle: {e}")

        if USE_FALLBACK_DATA:
            logger.warning("⚠️  Publishing fallback sample data to MQTT...")
            try:
                publish(
                    payload=FALLBACK_F1_DATA,
                    topic=F1_LIVE_DATA_TOPIC,
                    qos=1,
                    client=client,
                    retain=False
                )
                logger.info(f"✅ Successfully published fallback data ({len(FALLBACK_F1_DATA)} records) to AWS IoT Core")
                return True
            except Exception as fallback_error:
                logger.error(f"❌ Failed to publish fallback data: {fallback_error}")
                return False
        else:
            logger.warning("⚠️  Skipping fallback data publish (USE_FALLBACK_DATA=False)")
            return False


def run_continuous_publisher(interval: int = PUBLISH_INTERVAL) -> None:
    """
    Run the publisher continuously at specified interval using a persistent client connection.

    Args:
        interval (int): Time in seconds between publishes. Defaults to 10 (for testing)
    """
    global mqtt_client

    logger.info(f"🚀 Starting F1 Live Data Publisher (interval: {interval}s)")
    logger.info(f"📍 Publishing to topic: {F1_LIVE_DATA_TOPIC}")

    # Create persistent client connection (reused for all publishes)
    logger.info("🔌 Establishing persistent connection to AWS IoT Core...")
    mqtt_client = build_client(client_id="ps-f1-live-publisher")
    logger.info("✅ Connected! Ready to publish.")

    publish_count = 0
    error_count = 0

    try:
        while True:
            publish_count += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"📊 Publication cycle #{publish_count}")
            logger.info(f"{'='*60}")

            success = publish_f1_live_data(mqtt_client)

            if not success:
                error_count += 1
                logger.warning(f"⚠️  Error count: {error_count}")

            logger.info(f"⏰ Next publish in {interval} seconds...")
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("\n🛑 Publisher stopped by user (Ctrl+C)")
        logger.info(f"📈 Statistics:")
        logger.info(f"   Total publishes: {publish_count}")
        logger.info(f"   Errors: {error_count}")
        logger.info(f"   Success rate: {((publish_count - error_count) / publish_count * 100):.1f}%")

        # Cleanup
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            logger.info("🔌 Disconnected from AWS IoT Core")


if __name__ == "__main__":
    logger.info("🎬 F1 Live Data Publisher Starting...")
    run_continuous_publisher(interval=PUBLISH_INTERVAL)

