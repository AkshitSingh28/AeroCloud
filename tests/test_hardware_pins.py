from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from aeroos.hardware_config import (
    PinValidationError,
    load_hardware_profile,
    pin_catalog,
    update_pins,
    validate_pins,
)

PROFILE = """# AeroOS Raspberry Pi 4 bring-up profile

[display]
model = "SC1227"
width = 800

[dht22]
bcm_gpio = 18
physical_pin = 12
power = "3.3V"

[ds18b20]
bcm_gpio = 4
pull_up_ohms = 4700

[pcf8591]
i2c_bus = 1
address = 0x48

[outputs]
mist_bcm_gpio = 17
fan_bcm_gpio = 25
active_low = true

[safety]
actuator_master_enable = false
"""


@pytest.fixture()
def profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "hardware.toml"
    path.write_text(PROFILE, encoding="utf-8")
    return path


def test_reserved_i2c_lines_are_rejected() -> None:
    """BCM2/3 carry the ADC; reassigning them silently kills the light sensor."""
    with pytest.raises(PinValidationError) as excinfo:
        validate_pins({"mist_gpio": 2})
    assert "I2C1 SDA" in excinfo.value.errors[0]


def test_uart_lines_are_rejected() -> None:
    with pytest.raises(PinValidationError, match="UART"):
        validate_pins({"fan_gpio": 14})


def test_out_of_range_pins_are_rejected() -> None:
    with pytest.raises(PinValidationError, match="outside the usable range"):
        validate_pins({"fan_gpio": 40})


def test_two_functions_cannot_share_one_line() -> None:
    with pytest.raises(PinValidationError, match="assigned to both"):
        validate_pins({"mist_gpio": 22, "fan_gpio": 22})


def test_valid_reassignment_passes() -> None:
    assert validate_pins({"mist_gpio": 23, "fan_gpio": 24}) == []


def test_moving_the_1wire_pin_warns_about_the_device_tree() -> None:
    warnings = validate_pins({"ds18b20_gpio": 22})
    assert any("dtoverlay=w1-gpio,gpiopin=22" in warning for warning in warnings)


def test_spi_lines_warn_without_blocking() -> None:
    warnings = validate_pins({"mist_gpio": 9})
    assert any("SPI0" in warning for warning in warnings)


def test_update_rewrites_only_the_pins(profile_path: Path) -> None:
    update_pins(profile_path, {"mist_gpio": 23, "dht22_gpio": 21})
    payload = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    assert payload["outputs"]["mist_bcm_gpio"] == 23
    assert payload["dht22"]["bcm_gpio"] == 21
    # Everything else survives the rewrite.
    assert payload["outputs"]["fan_bcm_gpio"] == 25
    assert payload["outputs"]["active_low"] is True
    assert payload["display"]["model"] == "SC1227"
    assert payload["pcf8591"]["address"] == 0x48
    assert payload["safety"]["actuator_master_enable"] is False
    assert payload["ds18b20"]["pull_up_ohms"] == 4700


def test_update_is_readable_by_the_loader(profile_path: Path) -> None:
    update_pins(profile_path, {"fan_gpio": 26})
    profile = load_hardware_profile(profile_path)
    assert profile.fan_gpio == 26
    assert profile.mist_gpio == 17
    assert profile.actuator_master_enable is False


def test_an_invalid_change_leaves_the_file_untouched(profile_path: Path) -> None:
    original = profile_path.read_text(encoding="utf-8")
    with pytest.raises(PinValidationError):
        update_pins(profile_path, {"mist_gpio": 3})
    assert profile_path.read_text(encoding="utf-8") == original


def test_catalog_marks_the_actuator_lines(profile_path: Path) -> None:
    catalog = pin_catalog(load_hardware_profile(profile_path))
    actuators = {entry["field"] for entry in catalog if entry["actuator"]}
    assert actuators == {"mist_gpio", "fan_gpio"}
    assert {entry["value"] for entry in catalog} == {18, 4, 17, 25}
