#!/bin/bash
# Shell commands using mosquitto_pub (install: sudo apt install mosquitto-clients)
# These work without any Python dependencies.

# Turn GPIO 5 ON
mosquitto_pub -h localhost -t "garden/relay/set" -m '{"pin":5,"state":1}'

# Turn GPIO 5 OFF
mosquitto_pub -h localhost -t "garden/relay/set" -m '{"pin":5,"state":0}'

# Turn GPIO 6 ON
mosquitto_pub -h localhost -t "garden/relay/set" -m '{"pin":6,"state":1}'

# Turn GPIO 7 ON
mosquitto_pub -h localhost -t "garden/relay/set" -m '{"pin":7,"state":1}'

# Watch all garden topics
mosquitto_sub -h localhost -t "garden/#" -v

# Get latest status
mosquitto_sub -h localhost -t "garden/status" -C 1
