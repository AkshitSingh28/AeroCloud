from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from .hardware import Hardware
from .hardware_config import load_hardware_profile
from .models import HardwareCapabilities, SensorSnapshot


class RaspberryPiHardware(Hardware):
    """Independent sensor adapters for the AeroOS Pi 4 bring-up profile.

    Output GPIO objects are not created at all while the actuator master enable is
    false. This is deliberate: a software bug cannot toggle relay inputs during
    the sensor/camera commissioning phase.
    """

    def __init__(self, config_path: Path | None = None, *, actuators_enabled: bool = False) -> None:
        try:
            import adafruit_dht
            import board
            from gpiozero import OutputDevice
            from smbus2 import SMBus
            from w1thermsensor import W1ThermSensor
        except ImportError as exc:
            raise RuntimeError(f"AeroOS Raspberry Pi hardware package is incomplete: {exc}") from exc

        self.profile = load_hardware_profile(config_path)
        self.actuators_enabled = bool(actuators_enabled and self.profile.actuator_master_enable)
        dht_pin = getattr(board, f"D{self.profile.dht22_gpio}")
        self._dht = adafruit_dht.DHT22(dht_pin, use_pulseio=False)
        self._solution_temperature = W1ThermSensor()
        self._light_bus = SMBus(self.profile.pcf8591_bus)
        self._output_device = OutputDevice
        self._mist: Any | None = None
        self._fan: Any | None = None
        if self.actuators_enabled:
            active_high = not self.profile.outputs_active_low
            self._mist = OutputDevice(
                self.profile.mist_gpio, active_high=active_high, initial_value=False
            )
            self._fan = OutputDevice(
                self.profile.fan_gpio, active_high=active_high, initial_value=False
            )
        self._last_temperature: float | None = None
        self._last_humidity: float | None = None
        self._last_climate_at = 0.0

    @property
    def capabilities(self) -> HardwareCapabilities:
        return HardwareCapabilities(
            climate=True,
            solution_temperature=True,
            light=True,
            camera=True,
            mist_output=self.actuators_enabled,
            fan_output=self.actuators_enabled,
        )

    @property
    def mist_pump_active(self) -> bool:
        return bool(self._mist and self._mist.value)

    @property
    def dosing_pump_active(self) -> bool:
        return False

    @property
    def fan_active(self) -> bool:
        return bool(self._fan and self._fan.value)

    def _read_climate(self) -> tuple[float | None, float | None]:
        try:
            temperature = self._dht.temperature
            humidity = self._dht.humidity
            if temperature is not None and humidity is not None:
                self._last_temperature = float(temperature)
                self._last_humidity = float(humidity)
                self._last_climate_at = time.monotonic()
        except RuntimeError:
            pass
        if time.monotonic() - self._last_climate_at > 10:
            return None, None
        return self._last_temperature, self._last_humidity

    def _read_solution_temperature(self) -> float | None:
        try:
            return float(self._solution_temperature.get_temperature())
        except Exception:
            return None

    def _read_light_percent(self) -> float | None:
        try:
            channel = self.profile.temt6000_channel & 0x03
            address = self.profile.pcf8591_address
            self._light_bus.write_byte(address, 0x40 | channel)
            self._light_bus.read_byte(address)  # discard the previous conversion
            raw = self._light_bus.read_byte(address)
            return max(0.0, min(100.0, (raw / 255.0) * 100.0))
        except OSError:
            return None

    def _read_sync(self) -> SensorSnapshot:
        temperature, humidity = self._read_climate()
        solution = self._read_solution_temperature()
        light = self._read_light_percent()
        return SensorSnapshot(
            air_temperature_c=round(temperature, 2) if temperature is not None else None,
            relative_humidity_percent=round(humidity, 2) if humidity is not None else None,
            light_percent=round(light, 1) if light is not None else None,
            solution_temperature_c=round(solution, 2) if solution is not None else None,
        )

    async def read_sensors(self) -> SensorSnapshot:
        return await asyncio.to_thread(self._read_sync)

    @staticmethod
    def _require_output(output: Any | None, name: str, active: bool) -> None:
        if active and output is None:
            raise RuntimeError(f"{name} output is disabled pending power commissioning")

    async def set_mist_pump(self, active: bool) -> None:
        self._require_output(self._mist, "mist relay", active)
        if self._mist is not None:
            self._mist.on() if active else self._mist.off()

    async def set_fan(self, active: bool) -> None:
        self._require_output(self._fan, "fan relay", active)
        if self._fan is not None:
            self._fan.on() if active else self._fan.off()

    async def set_dosing_pump(self, active: bool) -> None:
        if active:
            raise RuntimeError("nutrient dosing is not commissioned")

    async def set_mixer(self, active: bool) -> None:
        if active:
            raise RuntimeError("mixer is not commissioned")
