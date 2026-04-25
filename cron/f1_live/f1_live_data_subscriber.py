#!/usr/bin/env python3
"""
F1 Live Data Subscriber

Test subscriber to receive F1 live timing data from AWS IoT Core MQTT broker.
This will:
1. Connect to the MQTT broker
2. Receive the last retained message (if available)
3. Continue receiving new messages as they're published

Usage:
    python f1_live_data_subscriber.py
"""

import json
import time
from loguru import logger
from mqtt.ps_mqtt import build_client, F1_LIVE_DATA_TOPIC

# Global message counter
message_count = 0

def on_message_handler(client, userdata, message):
    """Handle incoming messages"""
    global message_count
    message_count += 1

    try:
        payload = json.loads(message.payload.decode('utf-8'))

        # If it's a list (F1 data)
        if isinstance(payload, list):
            logger.info(f"\n{'='*70}")
            logger.info(f"📨 Message #{message_count} received at {time.strftime('%H:%M:%S')}")
            logger.info(f"{'='*70}")
            logger.info(f"🏎️  Received {len(payload)} F1 driver records")
            logger.info(f"📍 Topic: {message.topic}")
            logger.info(f"⏱️  QoS: {message.qos}")
            logger.info(f"📌 Retained: {message.retain}")
            logger.info(f"\nDriver Standings:")
            for i, driver in enumerate(payload[:5]):
                logger.info(f"  {i+1}. {driver['First Name']} {driver['Last Name']} ({driver['Abbreviation']}) - {driver['Team']} Gap: {driver['Gap']}")
            if len(payload) > 5:
                logger.info(f"  ... and {len(payload)-5} more drivers")
            logger.info(f"")
        else:
            logger.info(f"📦 Received data: {json.dumps(payload, indent=2)}")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.info(f"Raw payload: {message.payload.decode('utf-8')[:100]}...")
    except Exception as e:
        logger.error(f"Error processing message: {e}")

def on_connect_handler(client, userdata, flags, reason_code, properties=None):
    """Called when client connects"""
    if reason_code == 0:
        logger.info(f"✅ Connected to AWS IoT Core")
    else:
        logger.error(f"❌ Connection failed with reason code: {reason_code}")

def on_disconnect_handler(client, userdata, flags, reason_code, properties=None):
    """Called when client disconnects"""
    logger.warning(f"⚠️  Disconnected from MQTT broker (reason code: {reason_code})")

logger.info("🎬 F1 Live Data Subscriber Starting...")
logger.info(f"📍 Subscribing to topic: {F1_LIVE_DATA_TOPIC}")
logger.info(f"⏳ Establishing connection to AWS IoT Core...\n")

try:
    # Build a persistent client
    client = build_client(client_id="ps-f1-live-subscriber")
    
    # Set message handlers IMMEDIATELY after client is created
    client.on_message = on_message_handler
    client.on_connect = on_connect_handler
    client.on_disconnect = on_disconnect_handler
    
    # Subscribe to the topic
    client.subscribe(F1_LIVE_DATA_TOPIC, qos=1)
    logger.info(f"✅ Subscribed to [{F1_LIVE_DATA_TOPIC}]")
    logger.info(f"⏳ Listening for messages (retained message will arrive first, then new publishes every 10s)...\n")
    
    # Start the event loop - this will block and listen for messages
    client.loop_forever()
    
except KeyboardInterrupt:
    logger.info("\n\n🛑 Subscriber stopped by user (Ctrl+C)")
    logger.info(f"📊 Statistics:")
    logger.info(f"   Total messages received: {message_count}")
    if message_count > 0:
        logger.info(f"   ✅ Successfully received messages!")
    else:
        logger.warning(f"   ⚠️  No messages received")
    client.loop_stop()
    client.disconnect()
    logger.info("🔌 Disconnected from broker")

