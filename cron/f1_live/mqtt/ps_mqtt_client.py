"""
ps_mqtt_client.py
-----------------
Standalone MQTT subscriber for AWS IoT Core.

Usage
-----
# Subscribe to the default topic (f1/live)
python ps_mqtt_client.py

# Subscribe to a specific topic
python ps_mqtt_client.py --topic f1/lap-by-lap

# Subscribe using a wildcard  (all f1 sub-topics)
python ps_mqtt_client.py --topic "f1/#"

# Subscribe with a custom QoS
python ps_mqtt_client.py --topic f1/live --qos 0
"""

import argparse
import json
import sys
import time
import signal

import paho.mqtt.client as mqtt
from loguru import logger

from ps_mqtt import (
    F1_LIVE_DATA_TOPIC,
    F1_LAP_BY_LAP_TOPIC,
    MQTT_ENDPOINT,
    MQTT_PORT,
    build_client,
)

# ── Logger setup ───────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="DEBUG",
)

# ── Global client reference (used for clean shutdown) ─────────────────────────
_client: mqtt.Client | None = None


# ── Message handler ────────────────────────────────────────────────────────────
def on_message(client: mqtt.Client, userdata: dict, message: mqtt.MQTTMessage) -> None:
    """
    Called every time a message arrives on a subscribed topic.
    Attempts to parse the payload as JSON; falls back to raw string.
    """
    raw = message.payload.decode("utf-8")

    try:
        payload = json.loads(raw)
        logger.info(
            f"\n{'─' * 60}\n"
            f"  Topic   : {message.topic}\n"
            f"  QoS     : {message.qos}\n"
            f"  Retain  : {message.retain}\n"
            f"  Payload :\n{json.dumps(payload, indent=4, ensure_ascii=False)}\n"
            f"{'─' * 60}"
        )
    except json.JSONDecodeError:
        logger.info(
            f"\n{'─' * 60}\n"
            f"  Topic   : {message.topic}\n"
            f"  QoS     : {message.qos}\n"
            f"  Retain  : {message.retain}\n"
            f"  Payload : {raw}\n"
            f"{'─' * 60}"
        )


# ── Subscription callback (runs on successful connect) ────────────────────────
def on_connect_and_subscribe(
    client: mqtt.Client,
    userdata: dict,
    flags,
    reason_code,
    properties=None,
) -> None:
    if reason_code == 0:
        topic = userdata.get("topic", F1_LIVE_DATA_TOPIC)
        qos   = userdata.get("qos", 1)
        client.subscribe(topic, qos=qos)
        logger.success(
            f"Connected to {MQTT_ENDPOINT}:{MQTT_PORT} — "
            f"subscribed to [{topic}] (QoS {qos})"
        )
    else:
        logger.error(f"Connection refused — reason code: {reason_code}")
        client.disconnect()


# ── Graceful shutdown ─────────────────────────────────────────────────────────
def _shutdown(sig, frame) -> None:
    logger.info("Interrupt received — disconnecting…")
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
    sys.exit(0)


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    global _client

    parser = argparse.ArgumentParser(
        description="AWS IoT Core MQTT subscriber",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--topic",
        default=F1_LIVE_DATA_TOPIC,
        help=f"MQTT topic to subscribe to (default: {F1_LIVE_DATA_TOPIC!r}). "
             f"Wildcards + and # are supported.",
    )
    parser.add_argument(
        "--qos",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="MQTT QoS level (default: 1)",
    )
    parser.add_argument(
        "--client-id",
        default=f"ps-subscriber-{int(time.time())}",
        help="MQTT client ID (default: auto-generated)",
    )
    args = parser.parse_args()

    # Register SIGINT / SIGTERM handlers
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(f"Starting MQTT subscriber | topic={args.topic!r} | qos={args.qos}")

    # Build TLS client and inject topic/qos via userdata
    _client = build_client(client_id=args.client_id)
    _client.user_data_set({"topic": args.topic, "qos": args.qos})

    # Override on_connect so we auto-subscribe after reconnects too
    _client.on_connect = on_connect_and_subscribe
    _client.on_message = on_message

    # Trigger the initial connection callbacks
    _client.loop_start()

    logger.info("Listening… press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown(None, None)


if __name__ == "__main__":
    main()

