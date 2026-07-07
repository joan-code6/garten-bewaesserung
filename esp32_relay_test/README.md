# ESP32-C3 Garden Irrigation Controller

## Firmware: v5 — Dynamic GPIO

Any valid GPIO (0-21) is accepted at runtime. No re-flashing needed to add new pins.
Blacklisted: GPIO 8, 9 (strapping pins), 18, 19 (USB/JTAG).

## Pin Mapping (Stand 27.06.2026)

| GPIO | Device                      |
|------|-----------------------------|
| 1    | Gartenschlauch unten rechts |
| 2    | Sprinkler Beet oben         |
| 3    | Bewaesserungsschlauch oben  |
| 4    | Hauptwasserversorgung       |
| 5    | (frei)                      |

Free pins: 0, 6, 7, 10, 20, 21

## Communication

Receives JSON commands over USB serial (115200 baud):
    {"pin":1,"state":1}   # ON
    {"pin":2,"state":0}   # OFF

Sends back:
    {"type":"state","pin":1,"state":1}     # per-pin acknowledgement
    {"type":"status","uptime":3600,"relays":{"1":1,"4":0,...}}  # every 60s

## Flashing

### Via PlatformIO (Windows):
    pio run --target upload

### Via Raspberry Pi (the Pi talks to ESP via USB):
    esptool --chip esp32c3 --port /dev/ttyACM0 --baud 460800 write_flash \
        0x0 bootloader.bin 0x8000 partitions.bin 0x10000 firmware.bin
