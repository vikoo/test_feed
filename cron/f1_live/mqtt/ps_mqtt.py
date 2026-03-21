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
    If *env_var* is set, decode its base64 value into a temp file and return that path.
    Otherwise return *fallback_path* directly (local dev workflow).
    """
    b64 = os.environ.get(env_var)
    if b64:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        tmp.write(base64.b64decode(b64))
        tmp.flush()
        tmp.close()
        _tmp_cert_files.append(tmp)
        logger.debug(f"Loaded {env_var} from environment variable → {tmp.name}")
        return tmp.name

    if not os.path.exists(fallback_path):
        raise FileNotFoundError(
            f"Certificate not found. Set the {env_var!r} environment variable "
            f"or place the file at: {fallback_path}"
        )
    logger.debug(f"Loaded {env_var} from file → {fallback_path}")
    return fallback_path


CA_CERT     = _cert_from_env_or_file(
    "MQTT_CA_CERT",
    os.path.join(_CERTS_DIR, "AmazonRootCA1.pem"),
)
DEVICE_CERT = _cert_from_env_or_file(
    "MQTT_DEVICE_CERT",
    os.path.join(_CERTS_DIR, "f09b447235130940b96864f11f4ace28e293746fade5c3875859cce42b7f1096-certificate.pem.crt"),
)
PRIVATE_KEY = _cert_from_env_or_file(
    "MQTT_PRIVATE_KEY",
    os.path.join(_CERTS_DIR, "f09b447235130940b96864f11f4ace28e293746fade5c3875859cce42b7f1096-private.pem.key"),
)

# ── Default topic ──────────────────────────────────────────────────────────────
F1_LIVE_DATA_TOPIC = "f1/live"
F1_LAP_BY_LAP_TOPIC = "f1/lap-by-lap"


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
    retain: bool = False,
    client: mqtt.Client | None = None,
) -> None:
    """
    Publish a single message and disconnect.

    Args:
        payload : dict (serialised to JSON) or raw string.
        topic   : MQTT topic string.
        qos     : Quality of service level (0 / 1 / 2).
        retain  : Whether the broker should retain the message.
        client  : Reuse an existing connected client, or None to create one.
    """
    _own_client = client is None
    if _own_client:
        client = build_client()  # blocks until connected

    body = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
    result = client.publish(topic, body, qos=qos, retain=retain)
    result.wait_for_publish(timeout=10)
    logger.info(f"Published to [{topic}]: {body}")

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

    if block:
        try:
            client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Subscriber stopped by user.")
            client.disconnect()

    return client


# ── Quick smoke-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample_payload = {
        "event": "test",
        "timestamp": time.time(),
        "message": "Hello from PS MQTT publisher!",
    }
    publish(sample_payload, topic=F1_LIVE_DATA_TOPIC)

