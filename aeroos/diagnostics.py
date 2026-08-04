"""Bring-up diagnostics: allow-listed shell probes and per-sensor health checks.

AeroOS deliberately does not expose an arbitrary shell. The control plane runs
as a service that can energize pumps, so a generic command endpoint would be a
remote-code-execution surface reachable from the kiosk network. Instead this
module publishes a fixed registry of read-only commands. Each entry is executed
with an explicit argv (never through a shell), has a hard timeout, and is
visible to the operator before it runs.

Additional commands can be declared per-appliance in the TOML file pointed at by
``AEROOS_DIAGNOSTICS_EXTRA`` without rebuilding the image.
"""

from __future__ import annotations

import asyncio
import glob
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .models import HardwareCapabilities, SensorSnapshot

ProbeState = Literal["ok", "degraded", "missing", "disabled", "not_installed", "unknown"]

COMMAND_TIMEOUT_SECONDS = 20
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class DiagnosticCommand:
    name: str
    label: str
    description: str
    argv: tuple[str, ...]
    category: str
    simulated_output: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "command": " ".join(self.argv),
            "available": shutil.which(self.argv[0]) is not None,
        }


@dataclass(slots=True)
class ProbeResult:
    id: str
    label: str
    interface: str
    expected: str
    state: ProbeState
    detail: str
    value: str | None = None
    remediation: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "interface": self.interface,
            "expected": self.expected,
            "state": self.state,
            "detail": self.detail,
            "value": self.value,
            "remediation": self.remediation,
        }


_SIM_I2CDETECT = """     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- 48 -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --
[simulator] PCF8591 answering at 0x48 as configured in hardware.toml."""

_SIM_W1 = """28-3c01f0954d2b
w1_bus_master1
[simulator] One DS18B20 present on the 1-Wire bus."""

_SIM_CAMERA = """Available cameras
-----------------
0 : arducam_64mp [9152x6944 10-bit] (/base/soc/i2c0mux/i2c@1/arducam_64mp@1a)
    Modes: 'SRGGB10_CSI2P' : 1920x1080 [15.00 fps]
                             9152x6944 [2.70 fps]
[simulator] Arducam B0483 enumerating in both live and still modes."""

_SIM_PINCTRL = """17: op -- dl | lo // GPIO17 = output, driven low (mist relay, de-energized)
18: ip pd -- | lo // GPIO18 = input (DHT22 data)
25: op -- dl | lo // GPIO25 = output, driven low (fan relay, de-energized)
 4: ip pu -- | hi // GPIO4  = input, pull-up (1-Wire)
[simulator] Both relay lines are parked low."""

_SIM_THROTTLED = """throttled=0x0
[simulator] No under-voltage or thermal throttling recorded."""

_SIM_JOURNAL = """-- Journal begins, simulated --
aeroos[612]: control engine started, actuator master enable = off
aeroos[612]: sensor poll ok, 4 of 9 capabilities available
aeroos[612]: reservoir level and delivery flow report null (no hardware)
[simulator] Real journal output appears here on the Raspberry Pi."""

BUILTIN_COMMANDS: tuple[DiagnosticCommand, ...] = (
    DiagnosticCommand(
        name="i2c-scan",
        label="Scan I2C bus",
        description="Lists every device answering on I2C bus 1. The PCF8591 should appear at 0x48.",
        argv=("i2cdetect", "-y", "1"),
        category="bus",
        simulated_output=_SIM_I2CDETECT,
    ),
    DiagnosticCommand(
        name="onewire-list",
        label="List 1-Wire devices",
        description="Shows DS18B20 probes found on GPIO4. Each probe appears as 28-xxxxxxxxxxxx.",
        argv=("ls", "-1", "/sys/bus/w1/devices"),
        category="bus",
        simulated_output=_SIM_W1,
    ),
    DiagnosticCommand(
        name="gpio-state",
        label="Read GPIO states",
        description="Current direction and level of every GPIO. Relay lines must read low while uncommissioned.",
        argv=("pinctrl", "get"),
        category="bus",
        simulated_output=_SIM_PINCTRL,
    ),
    DiagnosticCommand(
        name="camera-list",
        label="Enumerate cameras",
        description="Confirms the Arducam B0483 is detected on CSI and advertises the 64 MP still mode.",
        argv=("rpicam-hello", "--list-cameras"),
        category="camera",
        simulated_output=_SIM_CAMERA,
    ),
    DiagnosticCommand(
        name="camera-gate-log",
        label="Camera gate log",
        description="Output of the boot-time camera commissioning gate, including why it failed.",
        argv=("journalctl", "-u", "aeroos-camera-gate", "-n", "120", "--no-pager"),
        category="camera",
        simulated_output=_SIM_JOURNAL,
    ),
    DiagnosticCommand(
        name="service-status",
        label="Control service status",
        description="systemd state, restart count, and the most recent log lines for aeroos.service.",
        argv=("systemctl", "status", "aeroos", "--no-pager"),
        category="service",
        simulated_output=_SIM_JOURNAL,
    ),
    DiagnosticCommand(
        name="service-log",
        label="Control service log",
        description="Last 200 journal lines from the control engine. Start here when a sensor drops out.",
        argv=("journalctl", "-u", "aeroos", "-n", "200", "--no-pager"),
        category="service",
        simulated_output=_SIM_JOURNAL,
    ),
    DiagnosticCommand(
        name="kernel-log",
        label="Kernel messages",
        description="Recent kernel ring buffer. I2C and 1-Wire wiring faults surface here first.",
        argv=("journalctl", "-k", "-n", "200", "--no-pager"),
        category="service",
        simulated_output=_SIM_JOURNAL,
    ),
    DiagnosticCommand(
        name="boot-config",
        label="Boot configuration",
        description="Reads /boot/firmware/config.txt to confirm the i2c, 1-Wire, and camera overlays.",
        argv=("cat", "/boot/firmware/config.txt"),
        category="system",
        simulated_output=(
            "dtparam=i2c_arm=on\n"
            "dtoverlay=w1-gpio,gpiopin=4\n"
            "camera_auto_detect=1\n"
            "display_auto_detect=1\n"
            "dtoverlay=vc4-kms-v3d\n"
            "[simulator] Overlays required by the AeroOS hardware profile."
        ),
    ),
    DiagnosticCommand(
        name="power-health",
        label="Power and thermal health",
        description="Under-voltage and throttling flags. 0x0 means the 5 V supply held up.",
        argv=("vcgencmd", "get_throttled"),
        category="system",
        simulated_output=_SIM_THROTTLED,
    ),
    DiagnosticCommand(
        name="soc-temperature",
        label="SoC temperature",
        description="Raspberry Pi core temperature.",
        argv=("vcgencmd", "measure_temp"),
        category="system",
        simulated_output="temp=47.2'C\n[simulator] Nominal.",
    ),
    DiagnosticCommand(
        name="storage",
        label="Storage usage",
        description="Free space per filesystem. /var/lib/aeroos holds telemetry and captures.",
        argv=("df", "-h"),
        category="system",
        simulated_output=(
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/mmcblk0p2  2.4G  1.6G  700M  70% /\n"
            "/dev/mmcblk0p4   12G  240M   11G   3% /var/lib/aeroos\n"
            "[simulator] Data partition has headroom."
        ),
    ),
    DiagnosticCommand(
        name="network",
        label="Network interfaces",
        description="Link state and addresses for every interface.",
        argv=("ip", "-brief", "addr"),
        category="system",
        simulated_output=(
            "lo       UNKNOWN  127.0.0.1/8\n"
            "wlan0    UP       192.168.1.42/24\n"
            "[simulator] Kiosk reaches the API over loopback regardless of wlan0."
        ),
    ),
)


def _load_extra_commands(path: Path | None) -> tuple[DiagnosticCommand, ...]:
    """Load operator-declared commands from TOML.

    The file is part of the appliance image, not user input over the network, so
    it may declare any argv. It still runs without a shell and with the same
    timeout as the built-ins.
    """
    if path is None or not path.exists():
        return ()
    with path.open("rb") as source:
        payload = tomllib.load(source)
    extra: list[DiagnosticCommand] = []
    for entry in payload.get("command", []):
        argv = tuple(str(item) for item in entry.get("argv", ()))
        name = str(entry.get("name", "")).strip()
        if not name or not argv:
            continue
        extra.append(
            DiagnosticCommand(
                name=name,
                label=str(entry.get("label", name)),
                description=str(entry.get("description", "Operator-defined diagnostic.")),
                argv=argv,
                category=str(entry.get("category", "custom")),
                simulated_output=str(entry.get("simulated_output", "")),
            )
        )
    return tuple(extra)


class DiagnosticsService:
    def __init__(
        self,
        *,
        simulator: bool,
        hardware_profile: Any | None = None,
        extra_commands_path: Path | None = None,
        camera_gate_dir: Path = Path("/var/lib/aeroos/camera-gate"),
    ) -> None:
        self.simulator = simulator
        self.profile = hardware_profile
        self.camera_gate_dir = camera_gate_dir
        self._commands: dict[str, DiagnosticCommand] = {
            command.name: command
            for command in (*BUILTIN_COMMANDS, *_load_extra_commands(extra_commands_path))
        }

    # ---------------------------------------------------------------- commands

    def commands(self) -> list[dict[str, Any]]:
        return [command.as_dict() for command in self._commands.values()]

    async def run(self, name: str) -> dict[str, Any]:
        command = self._commands.get(name)
        if command is None:
            raise KeyError(name)
        started = datetime.now(timezone.utc)
        if self.simulator:
            return {
                "name": command.name,
                "command": " ".join(command.argv),
                "exit_code": 0,
                "output": command.simulated_output or "[simulator] No output.",
                "started_at": started.isoformat(),
                "duration_ms": 0,
                "simulated": True,
            }
        if shutil.which(command.argv[0]) is None:
            return {
                "name": command.name,
                "command": " ".join(command.argv),
                "exit_code": 127,
                "output": (
                    f"{command.argv[0]} is not installed on this appliance.\n"
                    "Install it or remove this diagnostic from the registry."
                ),
                "started_at": started.isoformat(),
                "duration_ms": 0,
                "simulated": False,
            }
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
            exit_code = process.returncode or 0
            output = stdout.decode("utf-8", errors="replace")
        except TimeoutError:
            exit_code = 124
            output = f"Command exceeded the {COMMAND_TIMEOUT_SECONDS}s diagnostic timeout and was killed."
        except OSError as exc:
            exit_code = 126
            output = f"Could not execute {command.argv[0]}: {exc}"
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n… output truncated …"
        return {
            "name": command.name,
            "command": " ".join(command.argv),
            "exit_code": exit_code,
            "output": output or "(no output)",
            "started_at": started.isoformat(),
            "duration_ms": round(duration),
            "simulated": False,
        }

    # ------------------------------------------------------------------ probes

    def _pin(self, attribute: str, fallback: int) -> int:
        return int(getattr(self.profile, attribute, fallback)) if self.profile else fallback

    def probe(
        self,
        snapshot: SensorSnapshot | None,
        capabilities: HardwareCapabilities,
        *,
        actuators_enabled: bool,
    ) -> list[ProbeResult]:
        return [
            self._probe_dht22(snapshot),
            self._probe_ds18b20(snapshot),
            self._probe_light(snapshot),
            self._probe_camera(capabilities),
            self._probe_relay("mist", "Mist relay", self._pin("mist_gpio", 17), capabilities.mist_output, actuators_enabled),
            self._probe_relay("fan", "Fan relay", self._pin("fan_gpio", 25), capabilities.fan_output, actuators_enabled),
            self._probe_absent(
                "reservoir_level",
                "Reservoir level",
                "Not wired",
                "Float switch or ultrasonic sensor",
                [
                    "This is one of the two interlocks that gate unsupervised misting.",
                    "Until it exists, automatic recirculation only runs inside a 30-minute supervised session.",
                ],
            ),
            self._probe_absent(
                "flow",
                "Delivery flow",
                "Not wired",
                "Inline flow sensor on the mist line",
                [
                    "Without flow feedback a spray is recorded as completed_unverified.",
                    "A dry-running pump cannot be detected until this is installed.",
                ],
            ),
            self._probe_absent(
                "ph", "pH", "Not wired", "Isolated pH interface board",
                ["Required before any pH-driven dosing decision is trustworthy."],
            ),
            self._probe_absent(
                "ec", "EC", "Not wired", "Isolated EC interface board",
                ["Nutrient dosing stays blocked until EC is commissioned."],
            ),
        ]

    def _probe_dht22(self, snapshot: SensorSnapshot | None) -> ProbeResult:
        pin = self._pin("dht22_gpio", 18)
        interface = f"1-wire proprietary · BCM{pin}"
        expected = "Temperature and humidity every 2 s"
        if snapshot is None:
            return ProbeResult(
                "dht22", "DHT22 chamber climate", interface, expected, "unknown",
                "No sensor snapshot has been taken yet.",
                remediation=["Wait for the first poll cycle, or check that aeroos.service is running."],
            )
        temperature = snapshot.air_temperature_c
        humidity = snapshot.relative_humidity_percent
        if temperature is None or humidity is None:
            return ProbeResult(
                "dht22", "DHT22 chamber climate", interface, expected, "missing",
                "No valid reading in the last 10 seconds.",
                remediation=[
                    f"Confirm the data line is on BCM{pin} (physical pin 12), not pin {pin}.",
                    "DHT22 needs a 4.7k–10k pull-up between DATA and 3.3 V.",
                    "Power the sensor from 3.3 V. The 5 V rail will damage the GPIO input.",
                    "The DHT22 protocol is timing sensitive — a single failed read is normal, a persistent one is wiring.",
                    "Run 'Read GPIO states' and confirm BCM%d shows as an input." % pin,
                ],
            )
        return ProbeResult(
            "dht22", "DHT22 chamber climate", interface, expected, "ok",
            "Climate readings are fresh.",
            value=f"{temperature:.1f} °C · {humidity:.0f}% RH",
        )

    def _probe_ds18b20(self, snapshot: SensorSnapshot | None) -> ProbeResult:
        pin = self._pin("ds18b20_gpio", 4)
        interface = f"1-Wire · BCM{pin}"
        expected = "Solution temperature every 2 s"
        devices = sorted(glob.glob("/sys/bus/w1/devices/28-*")) if not self.simulator else ["28-simulated"]
        value = snapshot.solution_temperature_c if snapshot else None
        if not devices:
            return ProbeResult(
                "ds18b20", "DS18B20 solution probe", interface, expected, "missing",
                "No 28-* device present on the 1-Wire bus.",
                remediation=[
                    "Add 'dtoverlay=w1-gpio,gpiopin=4' to /boot/firmware/config.txt and reboot.",
                    "A 4.7k pull-up from DATA to 3.3 V is mandatory — the bus will not enumerate without it.",
                    "Check the probe wiring: red 3.3 V, black ground, yellow data.",
                    "Run 'List 1-Wire devices' to see the raw bus contents.",
                ],
            )
        if value is None:
            return ProbeResult(
                "ds18b20", "DS18B20 solution probe", interface, expected, "degraded",
                f"Bus enumerates ({len(devices)} device(s)) but no temperature was read.",
                remediation=[
                    "A reading of 85.0 °C means the probe powered up but never completed a conversion.",
                    "Check for a marginal pull-up or excessive cable length.",
                ],
            )
        return ProbeResult(
            "ds18b20", "DS18B20 solution probe", interface, expected, "ok",
            f"{len(devices)} probe(s) enumerated.", value=f"{value:.1f} °C",
        )

    def _probe_light(self, snapshot: SensorSnapshot | None) -> ProbeResult:
        address = self._pin("pcf8591_address", 0x48)
        channel = self._pin("temt6000_channel", 0)
        interface = f"I2C bus 1 · PCF8591 0x{address:02x} · A{channel}"
        expected = "Ambient light percentage every 2 s"
        value = snapshot.light_percent if snapshot else None
        if value is None:
            return ProbeResult(
                "temt6000", "TEMT6000 ambient light", interface, expected, "missing",
                "The ADC did not answer on the I2C bus.",
                remediation=[
                    "Run 'Scan I2C bus' — the PCF8591 must appear at 0x%02x." % address,
                    "If the scan is empty, enable I2C with 'dtparam=i2c_arm=on' and reboot.",
                    "If a device appears at a different address, update pcf8591.address in hardware.toml.",
                    "SDA is BCM2 (pin 3) and SCL is BCM3 (pin 5). Both need 3.3 V logic.",
                    "The PCF8591 is 8-bit — a stuck reading of 0 or 255 means the analog input is rail-bound.",
                ],
            )
        return ProbeResult(
            "temt6000", "TEMT6000 ambient light", interface, expected, "ok",
            "ADC conversions are completing.", value=f"{value:.0f}%",
        )

    def _probe_camera(self, capabilities: HardwareCapabilities) -> ProbeResult:
        interface = "CSI-2 · Arducam B0483"
        expected = "1920x1080 at 15 fps live, 9152x6944 still"
        if self.simulator:
            return ProbeResult(
                "camera", "Arducam B0483", interface, expected, "ok",
                "Simulator serves an animated SVG feed instead of CSI frames.",
                value="Simulated",
            )
        passed_at = self.camera_gate_dir / "passed-at"
        if passed_at.exists():
            return ProbeResult(
                "camera", "Arducam B0483", interface, expected, "ok",
                f"Boot gate passed at {passed_at.read_text(encoding='utf-8').strip()}.",
                value="Gate passed",
            )
        return ProbeResult(
            "camera", "Arducam B0483", interface, expected,
            "ok" if capabilities.camera else "missing",
            "The boot-time camera gate has not recorded a pass.",
            remediation=[
                "Run 'Enumerate cameras' — the B0483 must list the 9152x6944 mode.",
                "Check 'camera_auto_detect=1' in /boot/firmware/config.txt.",
                "Reseat the CSI ribbon; contacts face the board on both ends.",
                "Read 'Camera gate log' for the exact step that failed.",
            ],
        )

    def _probe_relay(
        self, probe_id: str, label: str, pin: int, capability: bool, actuators_enabled: bool
    ) -> ProbeResult:
        interface = f"Relay logic · BCM{pin}"
        expected = "Line parked low until power commissioning"
        if not actuators_enabled or not capability:
            return ProbeResult(
                probe_id, label, interface, expected, "disabled",
                "Actuator master enable is off, so no GPIO output object exists for this line.",
                value="Safe off",
                remediation=[
                    "This is the intended bring-up state — the relay cannot be driven by a software fault.",
                    "Set safety.actuator_master_enable = true in /etc/aeroos/hardware.toml only after the "
                    "dry-output gate in docs/VALIDATION.md passes.",
                ],
            )
        return ProbeResult(
            probe_id, label, interface, expected, "ok",
            "Output object created and parked low.", value="Armed",
            remediation=["Confirm with 'Read GPIO states' that the line reads low before connecting a load."],
        )

    @staticmethod
    def _probe_absent(
        probe_id: str, label: str, interface: str, expected: str, remediation: list[str]
    ) -> ProbeResult:
        return ProbeResult(
            probe_id, label, interface, expected, "not_installed",
            "No hardware is commissioned for this measurement.",
            remediation=remediation,
        )

    def summary(self, results: list[ProbeResult]) -> dict[str, int]:
        counts = {"ok": 0, "degraded": 0, "missing": 0, "disabled": 0, "not_installed": 0, "unknown": 0}
        for result in results:
            counts[result.state] = counts.get(result.state, 0) + 1
        return counts
