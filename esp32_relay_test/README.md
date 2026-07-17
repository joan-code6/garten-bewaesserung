# ESP32-C3 Garden Irrigation Controller

## Firmware v5 — Dynamic GPIO

You don't need to reflash just to add a new relay pin. Any GPIO from 0 to 21 works at runtime — except the ones the chip uses for itself (GPIO 8, 9, 18, 19 are blocked).

## Current pin setup (as of 27.06.2026)

| GPIO | What it controls          |
|------|---------------------------|
| 1    | Gartenschlauch unten rechts |
| 2    | Sprinkler Beet oben       |
| 3    | Bewaesserungsschlauch oben |
| 4    | Hauptwasserversorgung     |
| 5    | (free)                    |

Still free: 0, 6, 7, 10, 20, 21

## How it talks

Send JSON over USB serial (115200 baud):

```
{"pin":1,"state":1}   # turn it on
{"pin":2,"state":0}   # turn it off
```

It answers with:

```
{"type":"state","pin":1,"state":1}              # OK, done
{"type":"status","uptime":3600,"relays":{...}}  # every 60 seconds
```

## Flashing

### From Windows (PlatformIO):

```
pio run --target upload
```

### From the Raspberry Pi (via USB):

```
esptool --chip esp32c3 --port /dev/ttyACM0 --baud 460800 write_flash \
    0x0 bootloader.bin 0x8000 partitions.bin 0x10000 firmware.bin
```
