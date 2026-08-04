from __future__ import annotations

import asyncio
import math
import random
import time
from abc import ABC, abstractmethod

from .models import HardwareCapabilities, SensorSnapshot


class Hardware(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> HardwareCapabilities: ...

    @abstractmethod
    async def read_sensors(self) -> SensorSnapshot: ...

    @abstractmethod
    async def set_mist_pump(self, active: bool) -> None: ...

    @abstractmethod
    async def set_dosing_pump(self, active: bool) -> None: ...

    @abstractmethod
    async def set_mixer(self, active: bool) -> None: ...

    @abstractmethod
    async def set_fan(self, active: bool) -> None: ...

    @property
    @abstractmethod
    def mist_pump_active(self) -> bool: ...

    @property
    @abstractmethod
    def dosing_pump_active(self) -> bool: ...

    @property
    @abstractmethod
    def fan_active(self) -> bool: ...


class SimulatorHardware(Hardware):
    def __init__(self, *, seed: int = 42) -> None:
        self._random = random.Random(seed)
        self._started_at = time.monotonic()
        self._mist_pump = False
        self._dosing_pump = False
        self._mixer = False
        self._fan = False
        self.reservoir_percent = 72.0
        self.flow_fault = False
        self.sensor_fault = False
        self.ec_ms_cm = 1.52
        self._lock = asyncio.Lock()

    @property
    def mist_pump_active(self) -> bool:
        return self._mist_pump

    @property
    def dosing_pump_active(self) -> bool:
        return self._dosing_pump

    @property
    def fan_active(self) -> bool:
        return self._fan

    @property
    def capabilities(self) -> HardwareCapabilities:
        return HardwareCapabilities(
            climate=True,
            solution_temperature=True,
            light=True,
            camera=True,
            reservoir_level=True,
            flow=True,
            ph=True,
            ec=True,
            mist_output=True,
            fan_output=True,
            nutrient_dosing=True,
            mixer=True,
        )

    async def read_sensors(self) -> SensorSnapshot:
        async with self._lock:
            if self.sensor_fault:
                raise RuntimeError("simulated sensor bus unavailable")
            elapsed = time.monotonic() - self._started_at
            slow = math.sin(elapsed / 80)
            fast = math.sin(elapsed / 17)
            noise = self._random.uniform(-0.08, 0.08)
            if self._dosing_pump:
                self.ec_ms_cm = min(2.4, self.ec_ms_cm + 0.003)
            flow = 0.0 if self.flow_fault or not self._mist_pump else 1.8 + noise
            return SensorSnapshot(
                air_temperature_c=round(26.1 + slow * 0.8 + noise, 2),
                relative_humidity_percent=round(67 + fast * 3 + noise, 2),
                light_lux=round(12700 + max(0, slow) * 3400, 1),
                light_percent=round(54 + max(0, slow) * 20, 1),
                solution_temperature_c=round(22.8 + slow * 0.3, 2),
                ph=round(6.1 + fast * 0.03, 2),
                ec_ms_cm=round(self.ec_ms_cm + noise * 0.02, 3),
                reservoir_percent=round(self.reservoir_percent, 1),
                flow_lpm=round(max(0, flow), 2),
                power_voltage=12.1,
                battery_percent=96.0,
            )

    async def set_mist_pump(self, active: bool) -> None:
        async with self._lock:
            self._mist_pump = active
            if active:
                self.reservoir_percent = max(0, self.reservoir_percent - 0.02)

    async def set_dosing_pump(self, active: bool) -> None:
        async with self._lock:
            self._dosing_pump = active

    async def set_mixer(self, active: bool) -> None:
        async with self._lock:
            self._mixer = active

    async def set_fan(self, active: bool) -> None:
        async with self._lock:
            self._fan = active
