import ssl
import time
import json
import os
import base64
import tempfile
import threading
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── AWS IoT Core endpoint ──────────────────────────────────────────────────────
MQTT_ENDPOINT = "a1fhr7h222g16s-ats.iot.eu-west-2.amazonaws.com"
MQTT_PORT     = 8883
CLIENT_ID     = "ps-f1-live-publisher"

# ── Certificate resolution ─────────────────────────────────────────────────────
# Priority 1: env vars (base64-encoded) — used in CI / GitHub Actions
# Priority 2: local files in certs/     — used for local development
_CERTS_DIR = os.path.join(os.path.dirname(__file__), "..", "certs")

# Temp files are created once at module load and cleaned up on process exit
_tmp_cert_files: list[tempfile.NamedTemporaryFile] = []


def _cert_from_env_or_file(env_var: str, fallback_path: str) -> str:
    """
    Return a filesystem path to the certificate content.
    Priority 1: local files in certs/ (for local development)
    Priority 2: env vars (base64-encoded) via CI/GitHub Actions

    Args:
        env_var: Environment variable name for base64-encoded certificate
        fallback_path: Path to local certificate file

    Returns:
        Path to the certificate file
    """
    # Priority 1: Check for local file first
    if os.path.exists(fallback_path):
        logger.debug(f"Loaded {env_var} from file → {fallback_path}")
        return fallback_path

    # Priority 2: Fall back to environment variable
    b64 = os.environ.get(env_var)
    if b64:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        tmp.write(base64.b64decode(b64))
        tmp.flush()
        tmp.close()
        _tmp_cert_files.append(tmp)
        logger.debug(f"Loaded {env_var} from environment variable → {tmp.name}")
        return tmp.name

    # Neither local file nor env var found
    raise FileNotFoundError(
        f"Certificate not found. Place certificate at {fallback_path!r} "
        f"or set the {env_var!r} environment variable with base64-encoded content"
    )


CA_CERT     = _cert_from_env_or_file(
    "MQTT_CA_CERT",
    os.path.join(_CERTS_DIR, "AmazonRootCA1.pem"),
)
DEVICE_CERT = _cert_from_env_or_file(
    "MQTT_DEVICE_CERT",
    os.path.join(_CERTS_DIR, "device-certificate.pem.crt"),
)
PRIVATE_KEY = _cert_from_env_or_file(
    "MQTT_PRIVATE_KEY",
    os.path.join(_CERTS_DIR, "device-private.pem.key"),
)

# ── Default topic ──────────────────────────────────────────────────────────────
F1_LIVE_DATA_TOPIC = "f1/live"
F1_LAP_BY_LAP_TOPIC = "f1/lap-by-lap"

# ── Message retention ────────────────────────────────────────────────────────────
# When True, broker retains last published message and sends to new subscribers
RETAIN_LAST_MESSAGE = True  # Set to False to disable message retention


# ── Callbacks ──────────────────────────────────────────────────────────────────
def _on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info(f"Connected to AWS IoT Core at {MQTT_ENDPOINT}:{MQTT_PORT}")
    else:
        logger.error(f"Connection failed – reason code: {reason_code}")


def _on_disconnect(client, userdata, flags, reason_code, properties=None):
    logger.warning(f"Disconnected from MQTT broker (reason code: {reason_code})")


def _on_publish(client, userdata, mid, reason_code=None, properties=None):
    logger.debug(f"Message published (mid={mid})")


def _on_message(client, userdata, message):
    logger.info(f"[{message.topic}] {message.payload.decode('utf-8')}")


# ── Client factory ─────────────────────────────────────────────────────────────
def build_client(client_id: str = CLIENT_ID) -> mqtt.Client:
    """
    Create, configure, and return a *fully connected* paho MQTT client
    authenticated via mutual TLS against AWS IoT Core.

    Blocks until the TCP+TLS handshake is complete (or raises TimeoutError).
    """
    _connected = threading.Event()

    def _on_connect_wait(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info(f"Connected to AWS IoT Core at {MQTT_ENDPOINT}:{MQTT_PORT}")
            _connected.set()
        else:
            logger.error(f"Connection failed – reason code: {reason_code}")

    client = mqtt.Client(
        client_id=client_id,
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    # Attach TLS using the IoT certificates
    client.tls_set(
        ca_certs=CA_CERT,
        certfile=DEVICE_CERT,
        keyfile=PRIVATE_KEY,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )

    # Register callbacks
    client.on_connect    = _on_connect_wait
    client.on_disconnect = _on_disconnect
    client.on_publish    = _on_publish
    client.on_message    = _on_message

    client.connect(MQTT_ENDPOINT, MQTT_PORT, keepalive=60)
    client.loop_start()  # start background network thread

    # Block here until _on_connect fires — guarantees the broker is ready
    if not _connected.wait(timeout=15):
        client.loop_stop()
        raise TimeoutError(
            f"Could not connect to MQTT broker at {MQTT_ENDPOINT}:{MQTT_PORT} within 15 s"
        )

    return client


# ── High-level helpers ─────────────────────────────────────────────────────────
def publish(
    payload: dict | str,
    topic: str = F1_LIVE_DATA_TOPIC,
    qos: int = 1,
    retain: bool | None = None,
    client: mqtt.Client | None = None,
) -> None:
    """
    Publish a message to MQTT topic.

    When retain=True, the broker keeps the last message and sends it to new subscribers.
    This allows new clients to receive the latest data upon subscription.

    Args:
        payload : dict (serialised to JSON), list, or raw string.
        topic   : MQTT topic string.
        qos     : Quality of service level (0 / 1 / 2).
        retain  : Whether to retain message (default uses RETAIN_LAST_MESSAGE setting).
        client  : Reuse an existing connected client, or None to create one.
    """
    _own_client = client is None
    if _own_client:
        client = build_client()  # blocks until connected
    else:
        logger.debug("Using provided persistent client connection")

    # Use default retention setting if not specified
    if retain is None:
        retain = RETAIN_LAST_MESSAGE

    body = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else payload

    try:
        result = client.publish(topic, body, qos=qos, retain=retain)
        result.wait_for_publish(timeout=10)
        logger.info(f"Published to [{topic}] (retain={retain}): {body[:100]}...")
    except Exception as e:
        logger.error(f"Failed to publish: {e}")
        raise

    if _own_client:
        client.loop_stop()
        client.disconnect()


def subscribe(
    topic: str = F1_LIVE_DATA_TOPIC,
    qos: int = 1,
    client: mqtt.Client | None = None,
    block: bool = True,
) -> mqtt.Client:
    """
    Subscribe to *topic* and optionally block (loop_forever).

    When a client subscribes to a topic with retained messages, the broker
    automatically sends the last published (retained) message to the subscriber.

    Args:
        topic  : MQTT topic string (wildcards + / # supported).
        qos    : Quality of service level.
        client : Reuse an existing connected client, or None to create one.
        block  : If True, blocks until KeyboardInterrupt; otherwise returns client.

    Returns:
        The connected mqtt.Client instance (useful when block=False).
    """
    if client is None:
        client = build_client()

    client.subscribe(topic, qos=qos)
    logger.info(f"Subscribed to [{topic}]")
    logger.info(f"ℹ️  Waiting for retained message from broker (if available)...")

    if block:
        try:
            client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Subscriber stopped by user.")
            client.disconnect()

    return client


def get_subscription_info() -> dict:
    """
    Get information about message retention and subscriptions.

    Note: AWS IoT Core doesn't expose real-time subscription counts via MQTT.
    However, message retention ensures new subscribers get the latest data.

    Returns:
        Information about retention settings and usage
    """
    return {
        "retention_enabled": RETAIN_LAST_MESSAGE,
        "message_retention_description": (
            "When enabled, the MQTT broker retains the last published message "
            "for each topic and sends it to any new subscribers. This ensures "
            "new clients always receive the latest data immediately upon subscription."
        ),
        "monitoring_note": (
            "AWS IoT Core does not expose subscription counts via standard MQTT. "
            "To monitor subscriptions, use AWS CloudWatch or enable AWS IoT Core logs."
        ),
        "how_it_works": {
            "publisher": "Publishes message with retain=True → Broker stores it",
            "new_subscriber_1": "Connects and subscribes → Receives retained message",
            "new_subscriber_2": "Connects and subscribes → Also receives retained message",
            "next_publish": "New message published → Replaces retained message, sent to all subscribers"
        }
    }


# ── Quick smoke-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_payload = {
        "event": "test",
        "timestamp": time.time(),
        "message": "Hello from PS MQTT publisher!",
    }
    publish(sample_payload, topic=F1_LIVE_DATA_TOPIC)

