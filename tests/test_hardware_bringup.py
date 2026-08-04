from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from aeroos.control import AeroController, ControlError
from aeroos.database import Database
from aeroos.hardware import Hardware
from aeroos.models import HardwareCapabilities, SensorSnapshot
from aeroos.settings import Settings


class BringUpHardware(Hardware):
    def __init__(self, *, outputs: bool) -> None:
        self.outputs = outputs
        self._mist = False
        self._fan = False
        self.mist_energize_attempts = 0
        self.snapshot = SensorSnapshot(
            air_temperature_c=26,
            relative_humidity_percent=68,
            light_percent=52,
            solution_temperature_c=22,
        )

    @property
    def capabilities(self) -> HardwareCapabilities:
        return HardwareCapabilities(
            climate=True,
            solution_temperature=True,
            light=True,
            camera=True,
            mist_output=self.outputs,
            fan_output=self.outputs,
        )

    @property
    def mist_pump_active(self) -> bool:
        return self._mist

    @property
    def dosing_pump_active(self) -> bool:
        return False

    @property
    def fan_active(self) -> bool:
        return self._fan

    async def read_sensors(self) -> SensorSnapshot:
        return self.snapshot.model_copy(deep=True)

    async def set_mist_pump(self, active: bool) -> None:
        if active:
            self.mist_energize_attempts += 1
        if active and not self.outputs:
            raise RuntimeError("output disabled")
        self._mist = active

    async def set_fan(self, active: bool) -> None:
        if active and not self.outputs:
            raise RuntimeError("output disabled")
        self._fan = active

    async def set_dosing_pump(self, active: bool) -> None:
        if active:
            raise RuntimeError("not commissioned")

    async def set_mixer(self, active: bool) -> None:
        if active:
            raise RuntimeError("not commissioned")


def make_settings(
    tmp_path,
    *,
    actuators_enabled: bool,
    spray_duration_seconds: float = 2,
    spray_interval_seconds: float = 300,
    development_mist_limit_seconds: float = 2,
) -> Settings:
    return Settings(
        data_dir=tmp_path,
        simulator=False,
        operator_pin="0420",
        spray_duration_seconds=spray_duration_seconds,
        spray_interval_seconds=spray_interval_seconds,
        manual_spray_limit_seconds=2,
        minimum_flow_lpm=0.2,
        dosing_pulse_ml=1,
        dosing_hourly_limit_ml=5,
        dosing_daily_limit_ml=20,
        actuators_enabled=actuators_enabled,
        development_session_minutes=30,
        development_mist_limit_seconds=development_mist_limit_seconds,
    )


def make_controller(tmp_path, *, outputs: bool, master: bool) -> tuple[AeroController, BringUpHardware]:
    settings = make_settings(tmp_path, actuators_enabled=master)
    database = Database(settings.database_path)
    database.initialize(simulator=False, operator_pin="0420")
    database.set_setting("commissioned", "1")
    hardware = BringUpHardware(outputs=outputs)
    return AeroController(settings, database, hardware), hardware


def make_fast_automatic_controller(
    tmp_path,
) -> tuple[AeroController, BringUpHardware]:
    settings = make_settings(
        tmp_path,
        actuators_enabled=True,
        spray_duration_seconds=0.1,
        spray_interval_seconds=0.05,
        development_mist_limit_seconds=0.2,
    )
    database = Database(settings.database_path)
    database.initialize(simulator=False, operator_pin="0420")
    database.set_setting("commissioned", "1")
    hardware = BringUpHardware(outputs=True)
    return AeroController(settings, database, hardware), hardware


@pytest.mark.asyncio
async def test_missing_measurements_remain_nullable_and_degraded(tmp_path):
    controller, hardware = make_controller(tmp_path, outputs=False, master=False)
    await controller.start()
    try:
        assert controller.latest is not None
        assert controller.latest.ph is None
        assert controller.latest.ec_ms_cm is None
        assert controller.latest.reservoir_percent is None
        assert controller.latest.flow_lpm is None
        status = controller.status()
        assert status.state.value == "degraded"
        assert status.reason == "Development / Interlocks unavailable"
        assert status.missing_interlocks == ["reservoir level", "delivery flow"]
        assert status.actuators_enabled is False
    finally:
        await controller.stop()
        controller.database.close()


@pytest.mark.asyncio
async def test_master_disable_rejects_mist_without_gpio_energize(tmp_path):
    controller, hardware = make_controller(tmp_path, outputs=True, master=False)
    await controller.start()
    try:
        with pytest.raises(ControlError, match="master enable is off"):
            await controller.request_mist(2, "development check")
        assert hardware.mist_energize_attempts == 0
    finally:
        await controller.stop()
        controller.database.close()


@pytest.mark.asyncio
async def test_supervised_session_caps_unverified_mist_to_two_seconds(tmp_path):
    controller, hardware = make_controller(tmp_path, outputs=True, master=True)
    await controller.start()
    try:
        await controller.arm_development_session()
        with pytest.raises(ControlError, match="2-second hard limit"):
            await controller.request_mist(3, "development check")
        result = await controller.request_mist(2, "development check")
        assert result.accepted
        await asyncio.sleep(2.1)
        assert hardware.mist_pump_active is False
        assert controller.database.recent_sprays()[0]["outcome"] == "completed_unverified"
    finally:
        await controller.stop()
        controller.database.close()


@pytest.mark.asyncio
async def test_automatic_recirculation_toggle_arms_bounded_session_and_cycles(tmp_path):
    controller, hardware = make_fast_automatic_controller(tmp_path)
    await controller.start()
    try:
        assert controller.status().automation_enabled is False
        await controller.set_automatic_recirculation(True)
        armed = controller.status()
        assert armed.automation_enabled is True
        assert armed.development_session_expires_at is not None
        assert armed.next_spray_at is not None

        await asyncio.sleep(1.3)
        assert hardware.mist_energize_attempts >= 1
        assert hardware.mist_pump_active is False
        spray = controller.database.recent_sprays()[0]
        assert spray["reason"] == "automatic recirculation schedule"
        assert spray["duration_seconds"] == pytest.approx(0.1)

        await controller.set_automatic_recirculation(False)
        stopped = controller.status()
        assert stopped.automation_enabled is False
        assert stopped.development_session_expires_at is None
        assert stopped.next_spray_at is None
        assert hardware.mist_pump_active is False
    finally:
        await controller.stop()
        controller.database.close()


@pytest.mark.asyncio
async def test_automatic_toggle_cannot_bypass_disabled_actuator_master(tmp_path):
    controller, hardware = make_controller(tmp_path, outputs=True, master=False)
    await controller.start()
    try:
        with pytest.raises(ControlError, match="master enable is off"):
            await controller.set_automatic_recirculation(True)
        assert controller.status().automation_enabled is False
        assert hardware.mist_energize_attempts == 0
    finally:
        await controller.stop()
        controller.database.close()


@pytest.mark.asyncio
async def test_fan_hysteresis_is_dry_run_and_stale_climate_forces_off(tmp_path):
    controller, hardware = make_controller(tmp_path, outputs=True, master=True)
    await controller.start()
    try:
        await controller.arm_development_session()
        controller._fan_request_changed_at = datetime.now(timezone.utc) - timedelta(seconds=61)
        await controller._update_fan_policy(
            SensorSnapshot(air_temperature_c=29, relative_humidity_percent=70)
        )
        assert controller.fan_requested is True
        assert hardware.fan_active is True
        await controller._update_fan_policy(
            SensorSnapshot(air_temperature_c=None, relative_humidity_percent=None)
        )
        assert controller.fan_requested is False
        assert hardware.fan_active is False
    finally:
        await controller.stop()
        controller.database.close()
