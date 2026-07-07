#!/usr/bin/env python3
"""
Garden Irrigation MQTT Control.

As a library:
    from garden import Garden
    g = Garden()
    g.on(5)
    g.off(6)
    g.toggle(7)
    g.get(5)       # => True / False / None
    g.status()     # => dict with uptime, rssi, relays
    g.watch()      # live monitor (blocks)

    g = Garden(broker="192.168.1.50")  # non-local broker

As a CLI:
    python garden.py on 5
    python garden.py off 6
    python garden.py status
    python garden.py watch

Install on Raspi:
    sudo apt install mosquitto mosquitto-clients
    pip3 install paho-mqtt
"""

import sys
import json
import time
import paho.mqtt.client as mqtt

TOPIC_SET = "garden/relay/set"
TOPIC_STATE = "garden/relay/state"
TOPIC_STATUS = "garden/status"


class Garden:
    def __init__(self, broker="localhost", port=1883):
        self.broker = broker
        self.port = port

    # ----- commands -----

    def on(self, pin):
        self._send({"pin": pin, "state": 1})

    def off(self, pin):
        self._send({"pin": pin, "state": 0})

    def set(self, pin, state):
        self._send({"pin": pin, "state": 1 if state else 0})

    def toggle(self, pin):
        cur = self.get(pin)
        if cur:
            self.off(pin)
        else:
            self.on(pin)

    # ----- queries -----

    def get(self, pin, timeout=2):
        s = self.status(timeout)
        if s is None:
            return None
        return s.get("relays", {}).get(str(pin))

    def status(self, timeout=2):
        result = {}

        def on_message(client, userdata, msg):
            result["payload"] = msg.payload.decode()

        client = mqtt.Client()
        client.on_message = on_message
        client.connect(self.broker, self.port, 5)
        client.subscribe(TOPIC_STATUS)
        client.loop_start()
        time.sleep(timeout)
        client.loop_stop()
        client.disconnect()

        if "payload" in result:
            return json.loads(result["payload"])
        return None

    def watch(self):
        def on_connect(client, userdata, flags, rc):
            client.subscribe(TOPIC_STATE)
            client.subscribe(TOPIC_STATUS)
            print(f"Listening on {TOPIC_STATE} and {TOPIC_STATUS} ...\n")

        def on_message(client, userdata, msg):
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {msg.topic}  {msg.payload.decode()}")

        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(self.broker, self.port, 60)

        try:
            client.loop_forever()
        except KeyboardInterrupt:
            print("\nDone.")

    # ----- internals -----

    def _send(self, payload):
        client = mqtt.Client()
        client.connect(self.broker, self.port, 5)
        client.publish(TOPIC_SET, json.dumps(payload))
        client.disconnect()


# ================================================================
# CLI
# ================================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    g = Garden()
    act = sys.argv[1].lower()

    if act in ("on", "off", "set"):
        if len(sys.argv) != 3:
            print(f"Usage: python garden.py {act} <pin>")
            sys.exit(1)
        pin = int(sys.argv[2])
        if act == "on":
            g.on(pin)
        elif act == "off":
            g.off(pin)
        elif act == "set":
            state = int(sys.argv[3]) if len(sys.argv) > 3 else 1
            g.set(pin, state)
        print(f"GPIO {pin} → {'ON' if act != 'off' else 'OFF'}")

    elif act == "status":
        s = g.status()
        if s:
            print(json.dumps(s, indent=2))
        else:
            print("No status — is the ESP32 online?")

    elif act == "watch":
        g.watch()

    else:
        print(f"Unknown command: {act}")
        print(__doc__)
        sys.exit(1)
