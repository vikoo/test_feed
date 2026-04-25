# Message Retention & Subscriptions Guide

## Overview

AWS IoT Core supports **MQTT Message Retention** - a mechanism that ensures new subscribers receive the latest data immediately upon subscription.

---

## How Message Retention Works

### Scenario Diagram

```
Timeline:
─────────────────────────────────────────────────────────────────

Time 0: Publisher 1 connects and publishes "Message A" with retain=True
        ✅ AWS IoT Core stores "Message A" on topic f1/live
        
Time 1: Subscriber 1 subscribes to f1/live
        📨 Broker immediately sends stored "Message A" to Subscriber 1
        ✅ Subscriber 1 receives data instantly

Time 2: Subscriber 2 subscribes to f1/live
        📨 Broker immediately sends stored "Message A" to Subscriber 2
        ✅ Subscriber 2 also receives the latest data

Time 3: Publisher 1 publishes "Message B" with retain=True
        ✅ AWS IoT Core replaces "Message A" with "Message B"
        📨 Sent to all currently connected subscribers
        (and will be sent to any future subscribers)
```

---

## Implementation in This Project

### Publisher Side (F1 Live Data Publisher)

```python
# In ps_mqtt.py
RETAIN_LAST_MESSAGE = True  # Enables retention globally

# In f1_live_data_publisher.py
publish(
    payload=records,
    topic="f1/live",
    qos=1
    # retain parameter omitted → uses default RETAIN_LAST_MESSAGE=True
)
```

**What happens:**
1. 22 F1 driver records are published with `retain=True`
2. AWS IoT Core stores this as the "retained message"
3. Last 22 records are always available for new subscribers

### Subscriber Side

```python
# Any subscriber connecting after publisher
from mqtt.ps_mqtt import subscribe

client = subscribe(topic="f1/live", block=True)
```

**What happens:**
1. Client subscribes to `f1/live` topic
2. AWS IoT Core automatically sends the **last retained message** (22 F1 records)
3. Client receives data immediately, no waiting needed

---

## Configuration

### Enable/Disable Retention

Edit `/Users/vivekvekariya/Desktop/VIK/PS/PS/feed/cron/f1_live/mqtt/ps_mqtt.py`:

```python
# Line ~72

# To ENABLE retention (default)
RETAIN_LAST_MESSAGE = True   # ✅ New subscribers get last message

# To DISABLE retention
RETAIN_LAST_MESSAGE = False  # ❌ New subscribers don't get old messages
```

### Per-Message Override

```python
from mqtt.ps_mqtt import publish

# Force enable retention for this message (even if default is False)
publish(payload=data, topic="f1/live", retain=True)

# Force disable retention for this message (even if default is True)
publish(payload=data, topic="f1/live", retain=False)
```

---

## Subscription Monitoring

### Note: AWS IoT Core Limitations

❌ **AWS IoT Core does NOT expose real-time subscription counts** via standard MQTT protocol.

**Why?**
- MQTT protocol doesn't have built-in subscription count reporting
- AWS IoT Core follows MQTT standard
- Different brokers may have different monitoring approaches

### How to Monitor Subscriptions

#### Option 1: AWS CloudWatch (Recommended)

```bash
# View metrics in AWS Console:
1. Go to AWS IoT Core → Manage → Monitoring
2. Check "Subscriptions" metric
3. View graphs showing subscription activity over time
```

#### Option 2: Enable AWS IoT Core Logs

```bash
# Enable detailed logging:
1. AWS IoT Core → Settings → Log levels
2. Set to DEBUG to see connection/subscription events
3. View logs in CloudWatch Logs
```

#### Option 3: Application-Level Tracking (Manual)

Track subscriptions in your application code:

```python
# In your subscriber app
import time
from mqtt.ps_mqtt import subscribe, get_subscription_info

# Get retention info
info = get_subscription_info()
print(f"Retention enabled: {info['retention_enabled']}")

# Connect and track
client = subscribe(topic="f1/live", block=False)

# Your app logic...
# Keep a local count of connected subscribers
```

---

## Benefits of Message Retention

### ✅ Advantages

1. **Zero-delay data delivery** - New subscribers get instant data
2. **No data loss** - Even if publisher is down, latest data is stored
3. **Energy efficient** - Offline devices can get data when they reconnect
4. **Fault tolerance** - Brief network glitches don't cause data loss
5. **Scalability** - Doesn't matter how many subscribers there are

### ⚠️ Considerations

1. **Storage** - Each topic with retention uses broker storage
2. **Message size** - Large messages consume more storage
3. **Cleanup** - Old retained messages need manual cleanup if needed
4. **Multiple publishers** - Last publish wins (overwrites previous)

---

## Common Use Cases

### ✅ Perfect For (in this project)

```
F1 Live Data Publishing
├─ Latest timing data always available
├─ New clients get current standings immediately
├─ No need for historical data queries
└─ Refresh rate: every 60 seconds
```

### ❌ Not Ideal For

- High-frequency data (>100 messages/sec)
- Very large payloads (>100KB)
- Time-series data (need multiple retained messages)
- Temporary status updates

---

## Testing Retention

### Test 1: Publisher → Subscriber Flow

```bash
# Terminal 1: Start publisher
cd /Users/vivekvekariya/Desktop/VIK/PS/PS/feed
source venv/bin/activate
python cron/f1_live/f1_live_data_publisher.py

# Terminal 2: Start subscriber after ~5 seconds
from mqtt.ps_mqtt import subscribe
subscribe(topic="f1/live")

# Result: Subscriber immediately receives the last published data
```

### Test 2: Retention Persistence

```bash
# Step 1: Publish data
python -c "from mqtt.ps_mqtt import publish; publish({'test': 'data'}, topic='test/topic')"

# Step 2: Stop and restart application
# (simulate application crash/restart)

# Step 3: Subscribe
# You will still receive the published data because it was retained
```

---

## Monitoring in Current Setup

### Current Implementation

```
Publisher (f1_live_data_publisher.py)
│
├─ Every 60 seconds
├─ Scrapes F1 data or uses fallback
├─ Publishes with retain=True ✅
└─ AWS IoT stores as retained message

Subscriber (Your app)
│
├─ Connects to f1/live topic
├─ Receives last retained message immediately ✅
└─ Listens for new publishes
```

### Confirming Retention is Working

Look for this log output:

```
2026-04-25 23:05:44.876 | INFO | Published to [f1/live] (retain=True): [{"Pos": "1", ...
                                                       ^^^^^^^^
                                                    Shows retain=True
```

---

## Summary

| Feature | Status | Benefit |
|---------|--------|---------|
| Message Retention | ✅ **Enabled** | New subscribers get instant data |
| Subscription Count | ⚠️ Limited | Monitor via CloudWatch or logs |
| Data Persistence | ✅ **Enabled** | Last message always available |
| Multiple Subscribers | ✅ **Supported** | All get retained message on subscribe |
| Configurable | ✅ **Yes** | Toggle `RETAIN_LAST_MESSAGE` setting |

---

## Quick Reference

```python
# Enable retention globally
RETAIN_LAST_MESSAGE = True

# Publish with retention
publish(payload, topic, qos=1)  # Uses default

# Subscribe and get retained message
subscriber = subscribe(topic="f1/live")  # Gets last published data

# Check retention info
info = get_subscription_info()
print(info)
```

---

**Last Updated:** April 25, 2026  
**Related Files:**  
- `/cron/f1_live/mqtt/ps_mqtt.py` - MQTT configuration  
- `/cron/f1_live/f1_live_data_publisher.py` - Publisher implementation  

