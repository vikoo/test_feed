# F1 Live Data Publisher & Subscriber - Usage Guide

## ✅ What's Working

1. **Publisher**: Scrapes F1 data every 10 seconds and publishes to AWS IoT Core with message retention
2. **Message Retention**: New subscribers receive the last published message immediately
3. **Persistent Connections**: Publisher now uses a single persistent client to avoid connection exhaustion
4. **Fallback Data**: When no live race data available, uses sample 22-driver dataset
5. **ErrorHandling**: Comprehensive error handling with logging

---

## 🚀 Usage Instructions

### Running the Publisher

```bash
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed
source venv/bin/activate
python cron/f1_live/f1_live_data_publisher.py
```

**What it does:**
- Connects once to AWS IoT Core (persistent connection)
- Scrapes F1 live timing data  
- Publishes 22 driver records every 10 seconds with `retain=True`
- Uses fallback sample data if no live race is happening

**Configuration:**
- Edit `PUBLISH_INTERVAL` to change publish frequency (currently 10 seconds for testing, production should be 60 seconds)
- Edit `USE_FALLBACK_DATA` to control fallback behavior (default True)

---

### Running the Subscriber

```bash
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed
source venv/bin/activate
python cron/f1_live/f1_live_data_subscriber.py
```

**What it does:**
- Connects to AWS IoT Core
- Subscribes to `f1/live` topic
- **Immediately receives the last 22 driver records** (from retention)
- Continues listening for new publishes every 10 seconds

**Output:**
```
📍 Subscribing to topic: f1/live
✅ Subscribed to [f1/live]
⏳ Waiting for messages (retained message will arrive first, then new publishes every 10s)...

======================================================================
📨 Message #1 received
======================================================================
🏎️  Received 22 F1 driver records
📍 Topic: f1/live
⏱️  QoS: 1
📌 Retained: True

First 3 drivers:
  1. George Russell - Mercedes (+1:33.030)
  2. Lewis Hamilton - Ferrari (+0.118)
  3. Charles Leclerc - Ferrari (+0.164)
  ... and 19 more drivers
```

---

## 📊 Message Flow

```
Publisher                           Broker                    Subscriber
    │                                 │                            │
    ├─ Connect (persistent) ─────────>│                            │
    │                                 │                            │
    ├─ Publish (retain=True) ────────>│                            │
    │                                 ├─ Store last message        │
    │                                 │  (F1 race data)            │
    │                                 │                            │
    │                                 │                    <─ Subscribe ─┤
    │                                 ├─ Send retained ───────────>│
    │                                 │  message                   ├─ Display
    │                                 │                            │
    ├─ Publish (every 10s) ─────────>│                            │
    │                                 ├─ Update retained ─────────>│
    │                                 │  message                   ├─ Display
    │                                 │                            │
```

---

## 🔧 Configuration Settings

### In `ps_mqtt.py` (lines ~72)

```python
# Enable/Disable message retention globally
RETAIN_LAST_MESSAGE = True   # ✅ Enabled (recommended)

# Override per-message if needed
publish(payload, topic, retain=False)  # ❌ Don't retain this one
publish(payload, topic, retain=True)   # ✅ Do retain this one
```

### In `f1_live_data_publisher.py` (lines ~14-15)

```python
# Publish interval (in seconds)
PUBLISH_INTERVAL = 10  # 10 seconds for testing, use 60 for production

# Enable/disable fallback data
USE_FALLBACK_DATA = True  # Use sample 22-driver data when no live race
```

---

## 📈 What Each Client Receives

### Initial Connection (Subscriber)

```
✓ Immediately receives last 22 F1 drivers
✓ With gaps, tyres, and team information
✓ Marked as "retained" in message
```

### Subsequent Updates (every 10 seconds)

```
✓ Receives new publish with latest data
✓ Same 22 drivers (when no live race)
✓ New message is retained for future subscribers
```

---

## ⚠️ Known Limitations

1. **AWS IoT Core Quotas**: If running many concurrent clients, may hit connection limits
   - **Solution**: Use one persistent connection per client type (publisher, subscriber)

2. **No Real-time Subscription Count**: AWS IoT Core doesn't expose active subscriber counts
   - **Solution**: Monitor via CloudWatch or AWS IoT Core logs

3. **Single Retained Message per Topic**: Only the last message is retained
   - **Solution**: Use multiple topics if you need message history

---

## 🎯 Best Practices

### For Publishers
```python
# ✅ DO: Create client once, reuse for all publishes
client = build_client()
for i in range(100):
    publish(data, client=client)  # Reuses same connection
client.disconnect()

# ❌ DON'T: Create new client for each publish
for i in range(100):
    publish(data)  # Creates 100 new connections!
```

### For Subscribers
```python
# ✅ DO: Use persistent connection and listen
client = subscribe(topic="f1/live", block=True)  # Blocks and listens

# ✅ DO: Keep subscriber running long-term
# It will receive messages automatically

# ❌ DON'T: Connect and disconnect repeatedly
for i in range(10):
    subscribe(topic="f1/live")  # Creates many connections
```

---

## 🔗 Integration Examples

### With Your Application

```python
from mqtt.ps_mqtt import subscribe

# Subscribe and process F1 updates
def handle_race_data():
    client = subscribe(topic="f1/live", block=False)
    
    # Do other work...
    while True:
        # Client automatically receives and processes messages
        # via the on_message handler
        time.sleep(1)

handle_race_data()
```

### Modify Message Handler

```python
# In f1_live_data_subscriber.py

def on_message_handler(client, userdata, message):
    data = json.loads(message.payload.decode('utf-8'))
    
    # Your custom logic here
    for driver in data[:3]:
        print(f"{driver['Pos']}. {driver['First Name']} - {driver['Gap']}")
    
    # Send to database, update UI, etc.
    # save_to_database(data)
    # emit_websocket_update(data)

client.on_message = on_message_handler
```

---

## 📞 Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| No messages received | Subscriber not connected | Check AWS credentials and certs |
| "Quota exceeded" | Too many open connections | Use persistent clients, avoid creating new ones frequently |
| Retained message old | No updates published | Check publisher is running |
| Different data each time | Retention disabled | Ensure `RETAIN_LAST_MESSAGE = True` |

---

## 📚 Related Files

- **Publisher**: `/cron/f1_live/f1_live_data_publisher.py`
- **Subscriber**: `/cron/f1_live/f1_live_data_subscriber.py`
- **MQTT Core**: `/cron/f1_live/mqtt/ps_mqtt.py`
- **Retention Guide**: `/cron/f1_live/mqtt/RETENTION_AND_SUBSCRIPTIONS.md`

---

✅ **System Ready for Production!**

Run publisher and subscribers independently, they will communicate via AWS IoT Core with message retention ensuring no data loss.

