from __future__ import annotations

from pathlib import Path

import pytest

from aeroos.diagnostics import DiagnosticsService
from aeroos.hardware_config import HardwareProfile
from aeroos.models import HardwareCapabilities, SensorSnapshot


def service(**kwargs) -> DiagnosticsService:
    return DiagnosticsService(simulator=True, hardware_profile=HardwareProfile(), **kwargs)


def test_command_registry_never_runs_a_shell() -> None:
    for command in service()._commands.values():
        assert isinstance(command.argv, tuple) and command.argv
        joined = " ".join(command.argv)
        assert not any(token in joined for token in ("|", ";", "&&", ">", "$(", "`")), (
            f"{command.name} looks like a shell expression; diagnostics run argv directly"
        )


@pytest.mark.asyncio
async def test_unknown_command_is_rejected() -> None:
    with pytest.raises(KeyError):
        await service().run("rm-rf-slash")


@pytest.mark.asyncio
async def test_simulator_returns_labelled_output_without_executing() -> None:
    result = await service().run("i2c-scan")
    assert result["simulated"] is True
    assert result["exit_code"] == 0
    assert "0x48" in result["output"] or "48" in result["output"]


def test_probe_reports_missing_climate_with_wiring_hints() -> None:
    results = service().probe(
        SensorSnapshot(air_temperature_c=None, relative_humidity_percent=None),
        HardwareCapabilities(climate=True),
        actuators_enabled=False,
    )
    dht = next(item for item in results if item.id == "dht22")
    assert dht.state == "missing"
    assert any("pull-up" in hint for hint in dht.remediation)
    assert any("3.3 V" in hint for hint in dht.remediation)


def test_probe_reports_healthy_climate_with_a_value() -> None:
    results = service().probe(
        SensorSnapshot(air_temperature_c=26.4, relative_humidity_percent=71),
        HardwareCapabilities(climate=True),
        actuators_enabled=False,
    )
    dht = next(item for item in results if item.id == "dht22")
    assert dht.state == "ok"
    assert "26.4" in (dht.value or "")


def test_relays_report_disabled_while_the_master_enable_is_off() -> None:
    results = service().probe(
        SensorSnapshot(), HardwareCapabilities(), actuators_enabled=False
    )
    for probe_id in ("mist", "fan"):
        relay = next(item for item in results if item.id == probe_id)
        assert relay.state == "disabled"
        assert relay.value == "Safe off"


def test_uninstalled_measurements_are_not_reported_as_faults() -> None:
    results = service().probe(SensorSnapshot(), HardwareCapabilities(), actuators_enabled=False)
    for probe_id in ("reservoir_level", "flow", "ph", "ec"):
        probe = next(item for item in results if item.id == probe_id)
        assert probe.state == "not_installed"


def test_extra_commands_load_from_toml(tmp_path: Path) -> None:
    config = tmp_path / "diagnostics.toml"
    config.write_text(
        """
[[command]]
name = "list-usb"
label = "List USB devices"
description = "Operator-defined."
argv = ["lsusb"]
category = "custom"
""",
        encoding="utf-8",
    )
    names = {command["name"] for command in service(extra_commands_path=config).commands()}
    assert "list-usb" in names


def test_summary_counts_every_state() -> None:
    diagnostics = service()
    results = diagnostics.probe(SensorSnapshot(), HardwareCapabilities(), actuators_enabled=False)
    summary = diagnostics.summary(results)
    assert sum(summary.values()) == len(results)
