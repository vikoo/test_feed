# PS MQTT Module Documentation

## 📡 Overview

The **PS MQTT Module** (`ps_mqtt.py`) is a secure AWS IoT Core MQTT client for publishing and subscribing to F1 live race data and lap-by-lap telemetry. It provides high-level abstractions over the `paho-mqtt` library with mutual TLS authentication for production-grade security.

---

## 🎯 Purpose

This module enables real-time communication between your F1 data scraper and AWS IoT Core, allowing:
- **Publishing** F1 live timing updates to the cloud
- **Subscribing** to receive F1 data from other clients
- **Secure authentication** using device certificates
- **CI/CD friendly** certificate management (environment variables or local files)

---

## 🏗️ Architecture

### AWS IoT Core Connection
```
┌─────────────────┐
│  Your Script    │
│   (ps_mqtt.py)  │
└────────┬────────┘
         │ (TLS + mTLS)
         ▼
┌─────────────────────────────────────────────────┐
│ AWS IoT Core (eu-west-2)                        │
│ Endpoint: a1fhr7h222g16s-ats.iot.eu-west-2.    │
│ Port: 8883                                      │
└─────────────────────────────────────────────────┘
         │
         ├─► Topic: f1/live
         └─► Topic: f1/lap-by-lap
```

---

## 🔐 Certificate Management

### Two Certificate Resolution Modes

#### **Mode 1: Environment Variables (Production/CI-CD)**
For GitHub Actions, Docker, or cloud deployments:

```bash
export MQTT_CA_CERT="<base64-encoded-ca-cert>"
export MQTT_DEVICE_CERT="<base64-encoded-device-cert>"
export MQTT_PRIVATE_KEY="<base64-encoded-private-key>"
```

**Benefits:**
- ✅ No certificates stored in repository
- ✅ Secrets managed by CI/CD platform
- ✅ Secure for production deployments

#### **Mode 2: Local Files (Development)**
For local development:

```
cron/f1_live/mqtt/certs/
├── AmazonRootCA1.pem
├── f09b447235130940b96864f11f4ace28e293746fade5c3875859cce42b7f1096-certificate.pem.crt
└── f09b447235130940b96864f11f4ace28e293746fade5c3875859cce42b7f1096-private.pem.key
```

**Benefits:**
- ✅ Local testing without env vars
- ✅ No network calls during cert loading
- ⚠️ Requires secure storage

### Certificate Loading Order
1. Check for `MQTT_CA_CERT` environment variable → decode and create temp file
2. If not found, look for local file at `certs/AmazonRootCA1.pem`
3. Raise `FileNotFoundError` if neither exists

---

## 📚 Module Constants

```python
# AWS IoT Endpoint
MQTT_ENDPOINT = "a1fhr7h222g16s-ats.iot.eu-west-2.amazonaws.com"
MQTT_PORT = 8883

# Client identifier
CLIENT_ID = "ps-f1-live-publisher"

# MQTT Topics
F1_LIVE_DATA_TOPIC = "f1/live"        # Real-time live timing
F1_LAP_BY_LAP_TOPIC = "f1/lap-by-lap" # Lap-by-lap telemetry
```

---

## 🔧 Core Functions

### 1. `build_client(client_id=CLIENT_ID) → mqtt.Client`

Creates and connects a fully authenticated MQTT client.

**Parameters:**
- `client_id` (str, optional): Unique client identifier. Defaults to `"ps-f1-live-publisher"`

**Returns:**
- Connected `mqtt.Client` instance ready for publish/subscribe

**Behavior:**
- Initializes MQTT v5 client
- Loads TLS certificates
- Registers callback handlers
- Blocks for up to 15 seconds until connection established
- Starts background network thread

**Raises:**
- `TimeoutError`: If connection not established within 15 seconds
- `FileNotFoundError`: If certificates not found

**Example:**
```python
from ps_mqtt import build_client

client = build_client("my-custom-client-id")
# Client is now connected and ready to use
```

---

### 2. `publish(payload, topic=F1_LIVE_DATA_TOPIC, qos=1, retain=False, client=None) → None`

Publish a message to an MQTT topic.

**Parameters:**
- `payload` (dict | str): Message content
  - If `dict`: automatically serialized to JSON
  - If `str`: sent as-is
- `topic` (str): MQTT topic. Defaults to `"f1/live"`
- `qos` (int): Quality of Service level (0, 1, or 2). Defaults to `1`
- `retain` (bool): Whether broker should retain message. Defaults to `False`
- `client` (mqtt.Client | None): Existing client to reuse, or `None` to create new

**Behavior:**
- Creates new client if not provided
- Serializes dict to JSON with UTF-8 support (ensure_ascii=False)
- Waits up to 10 seconds for publish confirmation
- Logs published message
- Disconnects if client was created locally

**Example - Single Publish:**
```python
from ps_mqtt import publish

# Create client on-the-fly
publish({
    "driver": "Lewis Hamilton",
    "position": 1,
    "gap": "+0.000",
    "status": "racing"
}, topic="f1/live")
```

**Example - Batch Publish (Reuse Client):**
```python
from ps_mqtt import build_client, publish

client = build_client()

# Publish multiple messages without reconnecting
publish({"driver": "Max", "position": 1}, client=client)
publish({"driver": "Lewis", "position": 2}, client=client)
publish({"driver": "Charles", "position": 3}, client=client)

client.disconnect()
```

---

### 3. `subscribe(topic=F1_LIVE_DATA_TOPIC, qos=1, client=None, block=True) → mqtt.Client`

Subscribe to an MQTT topic and optionally listen for messages.

**Parameters:**
- `topic` (str): MQTT topic with optional wildcards (`+` for single level, `#` for multi-level). Defaults to `"f1/live"`
- `qos` (int): Quality of Service level. Defaults to `1`
- `client` (mqtt.Client | None): Existing client or `None` to create new
- `block` (bool): If `True`, blocks until `KeyboardInterrupt`. If `False`, returns immediately. Defaults to `True`

**Returns:**
- Connected `mqtt.Client` instance

**Behavior:**
- Creates new client if not provided
- Subscribes to topic
- If `block=True`: enters `loop_forever()` to listen for messages
  - Gracefully stops on `KeyboardInterrupt` (Ctrl+C)
- If `block=False`: returns client for manual event loop control

**Example - Blocking Subscriber:**
```python
from ps_mqtt import subscribe

# Listen for all F1 live updates (blocking)
subscribe(topic="f1/live", block=True)
```

**Example - Non-blocking Subscriber:**
```python
from ps_mqtt import subscribe

# Subscribe but obtain client for manual control
client = subscribe(topic="f1/+", block=False)  # Wildcard subscription

# Do other work...
time.sleep(10)

# Manual cleanup
client.disconnect()
```

**Topic Wildcards:**
```python
# Single level wildcard: only one path segment
subscribe("f1/+")  # Matches: f1/live, f1/lap-by-lap

# Multi-level wildcard: unlimited path segments (must be at end)
subscribe("f1/#")  # Matches: f1/live, f1/lap-by-lap, f1/driver/max, etc.
```

---

## 🔌 Callback Handlers

All callbacks are automatically registered and logged:

### `_on_connect(client, userdata, flags, reason_code, properties)`
Called when client connects to broker.
- Logs success if `reason_code == 0`
- Logs error with reason code if connection fails

### `_on_disconnect(client, userdata, flags, reason_code, properties)`
Called when client disconnects.
- Logs warning with reason code

### `_on_publish(client, userdata, mid, reason_code, properties)`
Called when message publish is confirmed by broker.
- Logs debug message with message ID (mid)

### `_on_message(client, userdata, message)`
Called when message is received on subscribed topic.
- Logs received message with topic and payload

---

## 📝 Usage Examples

### Example 1: Publish F1 Live Data

```python
from ps_mqtt import publish
import json

# Scrape F1 timing data and publish
f1_data = {
    "race": "Bahrain Grand Prix 2026",
    "drivers": [
        {"position": 1, "name": "Lewis Hamilton", "gap": "+0.000"},
        {"position": 2, "name": "Max Verstappen", "gap": "+1.234"},
        {"position": 3, "name": "Charles Leclerc", "gap": "+2.567"}
    ],
    "timestamp": 1619612398
}

publish(f1_data, topic="f1/live", qos=1, retain=False)
print("✅ F1 data published to AWS IoT Core!")
```

### Example 2: Continuous Publishing

```python
from ps_mqtt import build_client, publish
import time

def publish_lap_data_continuously():
    client = build_client("f1-lap-publisher")
    
    for lap_num in range(1, 58):  # F1 races are typically 57 laps
        lap_data = {
            "lap": lap_num,
            "sector1": 25.3,
            "sector2": 40.1,
            "sector3": 22.8,
            "total": 88.2,
            "status": "completed"
        }
        publish(lap_data, topic="f1/lap-by-lap", client=client)
        time.sleep(90)  # Wait 90 seconds between lap publishes
    
    client.disconnect()

publish_lap_data_continuously()
```

### Example 3: Subscribe and Process Messages

```python
from ps_mqtt import build_client, subscribe
import json
import threading

def process_f1_updates():
    def message_handler(client, userdata, msg):
        # Custom message handling
        data = json.loads(msg.payload.decode('utf-8'))
        print(f"Received: {data}")
    
    client = build_client("f1-subscriber")
    client.on_message = message_handler
    
    client.subscribe("f1/live", qos=1)
    client.loop_forever()

# Run in background thread
thread = threading.Thread(target=process_f1_updates, daemon=True)
thread.start()
```

### Example 4: Wildcard Subscriptions

```python
from ps_mqtt import subscribe

# Subscribe to all F1 topics
subscribe(topic="f1/#", block=True)
# Will receive messages from:
# - f1/live
# - f1/lap-by-lap
# - f1/anything/else
```

---

## 🚨 Error Handling

### Connection Timeout
```python
from ps_mqtt import build_client

try:
    client = build_client()
except TimeoutError as e:
    print(f"❌ Failed to connect to MQTT broker: {e}")
    # Handle offline scenario
```

### Certificate Not Found
```python
from ps_mqtt import build_client

try:
    client = build_client()
except FileNotFoundError as e:
    print(f"❌ Certificate missing: {e}")
    # Set environment variables or add cert files
```

### Publish Timeout
```python
from ps_mqtt import publish

try:
    publish({"test": "data"})
except Exception as e:
    print(f"❌ Publish failed: {e}")
```

---

## 📊 Quality of Service (QoS) Levels

### QoS 0 (At Most Once)
```python
publish(data, qos=0)  # Fire and forget
```
- Fastest but no guarantee of delivery
- Use for non-critical, high-frequency data

### QoS 1 (At Least Once) - **Recommended**
```python
publish(data, qos=1)  # Default
```
- Ensures delivery with possibility of duplicates
- Good balance between reliability and performance
- Recommended for most use cases

### QoS 2 (Exactly Once)
```python
publish(data, qos=2)  # Guaranteed delivery without duplicates
```
- Slowest but most reliable
- Use for critical data (race results, final standings)

---

## 🔐 Security Best Practices

### ✅ Do's
- ✅ Store certificates in environment variables for production
- ✅ Use QoS 1 or 2 for important data
- ✅ Enable message retention (`retain=True`) for state updates
- ✅ Use topic hierarchy for organization (e.g., `f1/live/drivers/max`)
- ✅ Rotate certificates periodically
- ✅ Use different client IDs for different services

### ❌ Don'ts
- ❌ Commit certificate files to Git repository
- ❌ Share private keys in logs or emails
- ❌ Use QoS 0 for critical race data
- ❌ Use default passwords or credentials
- ❌ Disable TLS verification

---

## 🧪 Testing

### Quick Smoke Test
```bash
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed
source venv/bin/activate
python cron/f1_live/mqtt/ps_mqtt.py
```

Output:
```
2026-04-25 19:45:12.345 | INFO | Connected to AWS IoT Core...
2026-04-25 19:45:12.567 | INFO | Published to [f1/live]: {...}
```

### Unit Testing
```python
import unittest
from ps_mqtt import build_client, publish, subscribe

class TestPSMQTT(unittest.TestCase):
    def setUp(self):
        self.client = None
    
    def tearDown(self):
        if self.client:
            self.client.disconnect()
    
    def test_client_connection(self):
        """Test successful client connection"""
        self.client = build_client()
        self.assertIsNotNone(self.client)
    
    def test_publish_dict(self):
        """Test publishing dict payload"""
        publish({"test": "data"})  # Should not raise
    
    def test_publish_string(self):
        """Test publishing string payload"""
        publish("test message")  # Should not raise

if __name__ == '__main__':
    unittest.main()
```

---

## 📦 Dependencies

```
paho-mqtt>=2.0.0      # MQTT client library
python-dotenv==1.2.2  # Environment variable loading
loguru==0.7.3         # Logging
```

All dependencies are in `cron/requirements.txt`.

---

## 🔗 AWS IoT Core Setup

### Prerequisites
1. AWS account with IoT Core service enabled
2. IoT device registered in AWS IoT Core
3. Downloaded certificate files:
   - CA certificate: `AmazonRootCA1.pem`
   - Device certificate: `{device-id}-certificate.pem.crt`
   - Private key: `{device-id}-private.pem.key`

### Endpoint Configuration
Replace `MQTT_ENDPOINT` in the module with your AWS IoT endpoint:
```python
# Find your endpoint in AWS Console:
# IoT Core → Settings → Device data endpoint
MQTT_ENDPOINT = "your-unique-id-ats.iot.region.amazonaws.com"
```

---

## 🚀 Integration with F1 Live Scraper

```python
# In f1_live_data.py
from cron.f1_live.mqtt.ps_mqtt import publish

# After scraping F1 data
json_str = scrape_f1_live_table()
records = json.loads(json_str)

# Publish to AWS IoT Core
publish(records, topic="f1/live", qos=1)
```

---

## 📋 Troubleshooting

| Issue | Solution |
|-------|----------|
| `FileNotFoundError: Certificate not found` | Set `MQTT_CA_CERT`/`MQTT_DEVICE_CERT`/`MQTT_PRIVATE_KEY` env vars OR add cert files to `certs/` folder |
| `TimeoutError: Could not connect within 15s` | Check network connectivity, verify endpoint URL, ensure certificates are valid |
| `Connection refused (13)` | Verify AWS IoT Core endpoint and port (8883) are correct |
| `Authentication failure` | Regenerate or update certificate files, ensure correct private key matches device cert |
| `Message not published` | Check topic permissions in AWS IoT policy, verify QoS setting |
| `No messages received` | Ensure subscriber is connected before publisher publishes, check topic name matches exactly |

---

## 📞 Support & Contributions

For issues or improvements:
1. Check AWS IoT Core documentation: https://docs.aws.amazon.com/iot-core/
2. Review paho-mqtt documentation: https://www.eclipse.org/paho/index.php?page=clients/python/docs/index.php
3. Review application logs with loguru

---

## 📄 License

Part of the Purple Sector F1 Feed application.

---

**Last Updated:** April 25, 2026  
**Module Version:** 1.0  
**Maintained By:** Purple Sector Team

