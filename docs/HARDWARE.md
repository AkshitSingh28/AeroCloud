# Raspberry Pi 4 bring-up contract

The source of truth is [`deploy/hardware.toml`](../deploy/hardware.toml).

| Function | Interface | Bring-up state |
|---|---|---|
| SC1227 official display | DSI, 800 x 480 landscape | Commissioned |
| DHT22 chamber climate | BCM18, physical pin 12, 3.3 V | Commissioned |
| DS18B20 solution temperature | BCM4, physical pin 7, 4.7 kOhm pull-up to 3.3 V | Commissioned |
| TEMT6000 ambient light | PCF8591 A0, I2C address `0x48`, 3.3 V | Commissioned |
| Arducam B0483 | CSI, 1080p15 live, 9152 x 6944 still | Camera gate required |
| Mist relay logic | BCM17, physical pin 11 | Disabled |
| Fan relay logic | BCM25, physical pin 22 | Disabled / policy dry-run |
| Reservoir level | No hardware | Unavailable |
| Delivery flow | No hardware | Unavailable |
| pH and EC | No production chemistry interface | Unavailable |
| Nutrient dosing and mixer | No commissioned hardware | Unavailable |

The Pi header 5 V rail may power the official display and approved low-current logic only. Sensors use 3.3 V. GPIO is 3.3 V-only. Pumps, fans, relay load contacts, the 5 V mister and the future 12 V domain remain disconnected.

`actuator_master_enable = false` is an electrical bring-up boundary. The physical adapter does not create relay GPIO output objects while that master is false.
