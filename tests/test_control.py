import asyncio
from pathlib import Path

import pytest

from aeroos.control import AeroController, ControlError
from aeroos.database import Database
from aeroos.hardware import SimulatorHardware
from aeroos.settings import Settings


def make_settings(path: Path) -> Settings:
    return Settings(
        data_dir=path,
        simulator=True,
        operator_pin="0420",
        spray_duration_seconds=0.5,
        spray_interval_seconds=300,
        manual_spray_limit_seconds=10,
        minimum_flow_lpm=0.2,
        dosing_pulse_ml=1,
        dosing_hourly_limit_ml=5,
        dosing_daily_limit_ml=20,
    )


@pytest.mark.asyncio
async def test_successful_mist_is_confirmed_and_logged(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    db.initialize(simulator=True, operator_pin="0420")
    hardware = SimulatorHardware()
    controller = AeroController(settings, db, hardware)
    await controller.start()
    result = await controller.request_mist(0.5, "test cycle")
    await asyncio.sleep(0.8)
    events = db.recent_sprays()
    assert result.accepted
    assert events[0]["outcome"] == "completed"
    assert events[0]["measured_flow_lpm"] >= 0.2
    assert not hardware.mist_pump_active
    await controller.stop()
    db.close()


@pytest.mark.asyncio
async def test_low_reservoir_blocks_misting(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    db.initialize(simulator=True, operator_pin="0420")
    hardware = SimulatorHardware()
    hardware.reservoir_percent = 2
    controller = AeroController(settings, db, hardware)
    await controller.start()
    with pytest.raises(ControlError, match="reservoir"):
        await controller.request_mist(0.5, "unsafe test")
    assert not hardware.mist_pump_active
    await controller.stop()
    db.close()


@pytest.mark.asyncio
async def test_no_flow_stops_pump_and_opens_alert(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    db.initialize(simulator=True, operator_pin="0420")
    hardware = SimulatorHardware()
    hardware.flow_fault = True
    controller = AeroController(settings, db, hardware)
    await controller.start()
    await controller.request_mist(0.5, "flow fault test")
    await asyncio.sleep(0.7)
    assert not hardware.mist_pump_active
    assert any(alert.code == "NO_FLOW" for alert in db.alerts(open_only=True))
    await asyncio.sleep(2.1)
    assert controller.state.value == "critical"
    with pytest.raises(ControlError, match="critical"):
        await controller.request_mist(0.5, "blocked retry")
    hardware.flow_fault = False
    await controller.reset_safety_lockout()
    assert controller.state.value == "safe"
    assert not any(alert.code == "NO_FLOW" for alert in db.alerts(open_only=True))
    await controller.stop()
    db.close()


@pytest.mark.asyncio
async def test_simultaneous_actuator_commands_are_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    db.initialize(simulator=True, operator_pin="0420")
    hardware = SimulatorHardware()
    controller = AeroController(settings, db, hardware)
    await controller.start()
    await controller.request_mist(0.5, "first command")
    with pytest.raises(ControlError, match="operation"):
        await controller.request_mist(0.5, "duplicate command")
    with pytest.raises(ControlError, match="operation"):
        await controller.request_dose(1, "overlapping command")
    await asyncio.sleep(0.8)
    assert len(db.recent_sprays()) == 1
    await controller.stop()
    db.close()
