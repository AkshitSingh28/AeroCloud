from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# BCM lines AeroOS refuses to reassign, with the reason shown to the operator.
RESERVED_GPIO: dict[int, str] = {
    0: "reserved for HAT ID EEPROM (ID_SD)",
    1: "reserved for HAT ID EEPROM (ID_SC)",
    2: "I2C1 SDA — carries the PCF8591 ADC",
    3: "I2C1 SCL — carries the PCF8591 ADC",
    14: "UART TXD — serial console",
    15: "UART RXD — serial console",
}

# Field name -> (TOML table, TOML key, human label)
EDITABLE_PINS: dict[str, tuple[str, str, str]] = {
    "dht22_gpio": ("dht22", "bcm_gpio", "DHT22 chamber climate"),
    "ds18b20_gpio": ("ds18b20", "bcm_gpio", "DS18B20 solution probe"),
    "mist_gpio": ("outputs", "mist_bcm_gpio", "Mist relay"),
    "fan_gpio": ("outputs", "fan_bcm_gpio", "Fan relay"),
}

MIN_GPIO, MAX_GPIO = 0, 27


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    dht22_gpio: int = 18
    ds18b20_gpio: int = 4
    pcf8591_bus: int = 1
    pcf8591_address: int = 0x48
    temt6000_channel: int = 0
    mist_gpio: int = 17
    fan_gpio: int = 25
    outputs_active_low: bool = True
    actuator_master_enable: bool = False
    development_session_minutes: int = 30
    camera_live_width: int = 1920
    camera_live_height: int = 1080
    camera_live_fps: int = 15
    camera_still_width: int = 9152
    camera_still_height: int = 6944


def load_hardware_profile(path: Path | None) -> HardwareProfile:
    if path is None or not path.exists():
        return HardwareProfile()
    with path.open("rb") as source:
        payload = tomllib.load(source)
    dht = payload.get("dht22", {})
    ds = payload.get("ds18b20", {})
    adc = payload.get("pcf8591", {})
    outputs = payload.get("outputs", {})
    safety = payload.get("safety", {})
    camera = payload.get("camera", {})
    return HardwareProfile(
        dht22_gpio=int(dht.get("bcm_gpio", 18)),
        ds18b20_gpio=int(ds.get("bcm_gpio", 4)),
        pcf8591_bus=int(adc.get("i2c_bus", 1)),
        pcf8591_address=int(adc.get("address", 0x48)),
        temt6000_channel=int(adc.get("temt6000_channel", 0)),
        mist_gpio=int(outputs.get("mist_bcm_gpio", 17)),
        fan_gpio=int(outputs.get("fan_bcm_gpio", 25)),
        outputs_active_low=bool(outputs.get("active_low", True)),
        actuator_master_enable=bool(safety.get("actuator_master_enable", False)),
        development_session_minutes=int(safety.get("development_session_minutes", 30)),
        camera_live_width=int(camera.get("live_width", 1920)),
        camera_live_height=int(camera.get("live_height", 1080)),
        camera_live_fps=int(camera.get("live_fps", 15)),
        camera_still_width=int(camera.get("still_width", 9152)),
        camera_still_height=int(camera.get("still_height", 6944)),
    )


class PinValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_pins(assignments: dict[str, int]) -> list[str]:
    """Check a proposed pin map. Returns non-blocking warnings; raises on errors.

    These lines drive relays and read sensors on a live appliance, so a bad map
    is rejected here rather than discovered as a silent misread at 3 a.m.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for field, value in assignments.items():
        if field not in EDITABLE_PINS:
            errors.append(f"{field} is not an editable pin")
            continue
        label = EDITABLE_PINS[field][2]
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{label} must be a BCM number")
            continue
        if not MIN_GPIO <= value <= MAX_GPIO:
            errors.append(f"{label}: BCM{value} is outside the usable range {MIN_GPIO}–{MAX_GPIO}")
        elif value in RESERVED_GPIO:
            errors.append(f"{label}: BCM{value} is {RESERVED_GPIO[value]}")

    seen: dict[int, str] = {}
    for field, value in assignments.items():
        if field not in EDITABLE_PINS or not isinstance(value, int):
            continue
        label = EDITABLE_PINS[field][2]
        if value in seen:
            errors.append(f"BCM{value} is assigned to both {seen[value]} and {label}")
        else:
            seen[value] = label

    if errors:
        raise PinValidationError(errors)

    if "ds18b20_gpio" in assignments and assignments["ds18b20_gpio"] != 4:
        warnings.append(
            f"1-Wire is bound by the device tree. Also change dtoverlay=w1-gpio,gpiopin="
            f"{assignments['ds18b20_gpio']} in /boot/firmware/config.txt and reboot, or the "
            "probe will not enumerate."
        )
    for field in ("mist_gpio", "fan_gpio"):
        if assignments.get(field) in (7, 8, 9, 10, 11):
            warnings.append(
                f"{EDITABLE_PINS[field][2]}: BCM{assignments[field]} is on the SPI0 bus. Safe "
                "while SPI is unused, but it will conflict if SPI is ever enabled."
            )
    return warnings


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _dump_toml(payload: dict[str, Any], header: str) -> str:
    """Minimal serializer for the flat table-of-scalars shape of hardware.toml."""
    lines = [header.rstrip(), ""]
    for key, value in payload.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")
    for table, contents in payload.items():
        if not isinstance(contents, dict):
            continue
        lines.append(f"[{table}]")
        for key, value in contents.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_pins(path: Path, assignments: dict[str, int]) -> list[str]:
    """Rewrite the pin assignments in hardware.toml, preserving everything else.

    The running adapter created its GPIO objects at start-up, so the change only
    takes effect after the control service restarts. The caller is responsible
    for saying so and for refusing while an actuator operation is in flight.
    """
    warnings = validate_pins(assignments)
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("rb") as source:
        payload = tomllib.load(source)
    for field, value in assignments.items():
        table, key, _ = EDITABLE_PINS[field]
        payload.setdefault(table, {})[key] = value
        # Keep the documented physical pin in step with the BCM line.
        if "physical_pin" in payload.get(table, {}):
            payload[table].pop("physical_pin")
    header = "# AeroOS Raspberry Pi 4 bring-up profile\n# Pin assignments edited from the appliance UI."
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_dump_toml(payload, header), encoding="utf-8")
    tmp.replace(path)
    return warnings


def pin_catalog(profile: HardwareProfile) -> list[dict[str, Any]]:
    """Everything the UI needs to render the pin editor."""
    current = {
        "dht22_gpio": profile.dht22_gpio,
        "ds18b20_gpio": profile.ds18b20_gpio,
        "mist_gpio": profile.mist_gpio,
        "fan_gpio": profile.fan_gpio,
    }
    return [
        {
            "field": field,
            "label": label,
            "table": table,
            "key": key,
            "value": current[field],
            "actuator": field in {"mist_gpio", "fan_gpio"},
        }
        for field, (table, key, label) in EDITABLE_PINS.items()
    ]
