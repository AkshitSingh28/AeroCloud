from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import __version__
from .database import Database
from .hardware import Hardware
from .models import CommandResult, SensorSnapshot, Severity, SystemState, SystemStatus
from .settings import Settings


class ControlError(RuntimeError):
    pass


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        for queue in tuple(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


class AeroController:
    MISSING_INTERLOCKS = ("reservoir_level", "flow")

    def __init__(self, settings: Settings, database: Database, hardware: Hardware) -> None:
        self.settings = settings
        self.database = database
        self.hardware = hardware
        self.events = EventBus()
        self.latest: SensorSnapshot | None = None
        self.state = SystemState.STARTING
        self.state_reason = "Starting control engine"
        self.next_spray_at: datetime | None = None
        self.last_successful_spray_at: datetime | None = None
        self.development_session_expires_at: datetime | None = None
        self.fan_requested = False
        self._fan_request_changed_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._poll_task: asyncio.Task[None] | None = None
        self._scheduler_task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None
        self._actuator_lock = asyncio.Lock()
        self._operation_pending = False
        self._stopping = False

    @property
    def actuators_enabled(self) -> bool:
        return bool(
            self.settings.actuators_enabled
            and (self.hardware.capabilities.mist_output or self.hardware.capabilities.fan_output)
        )

    @property
    def missing_interlocks(self) -> list[str]:
        capabilities = self.hardware.capabilities
        missing: list[str] = []
        if not capabilities.reservoir_level:
            missing.append("reservoir level")
        if not capabilities.flow:
            missing.append("delivery flow")
        return missing

    def development_session_active(self) -> bool:
        expiry = self.development_session_expires_at
        if expiry is None:
            return False
        if datetime.now(timezone.utc) >= expiry:
            self.development_session_expires_at = None
            return False
        return True

    async def arm_development_session(self) -> datetime:
        if not self.actuators_enabled:
            raise ControlError("actuator master enable is off; outputs remain physically disabled")
        self.development_session_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.settings.development_session_minutes
        )
        await self.events.publish(
            "development-session.armed",
            {"expires_at": self.development_session_expires_at.isoformat()},
        )
        return self.development_session_expires_at

    async def disarm_development_session(self, *, expired: bool = False) -> None:
        self.development_session_expires_at = None
        self.database.set_setting("automation_enabled", "0")
        self.next_spray_at = None
        await self.hardware.set_mist_pump(False)
        await self.hardware.set_fan(False)
        self.fan_requested = False
        await self.events.publish(
            "development-session.expired" if expired else "development-session.disarmed",
            {},
        )

    def _normal_state(self, reason: str | None = None) -> None:
        if self.missing_interlocks or not self.actuators_enabled:
            self.state = SystemState.DEGRADED
            self.state_reason = reason or "Development / Interlocks unavailable"
        else:
            self.state = SystemState.SAFE
            self.state_reason = reason or "All required systems available"

    async def start(self) -> None:
        await self.hardware.set_mist_pump(False)
        await self.hardware.set_dosing_pump(False)
        await self.hardware.set_mixer(False)
        await self.hardware.set_fan(False)
        # Physical AeroOS always boots with automatic recirculation off. The
        # operator must explicitly re-enable it from the local PIN-protected UI.
        if not self.settings.simulator or not self.actuators_enabled:
            self.database.set_setting("automation_enabled", "0")
        try:
            self.latest = await self._read_sensors_bounded()
            self.database.add_reading(self.latest)
            self._normal_state()
            if (
                self.actuators_enabled
                and not self.missing_interlocks
                and self.database.get_setting("automation_enabled") == "1"
            ):
                self.next_spray_at = datetime.now(timezone.utc) + timedelta(
                    seconds=self.settings.spray_interval_seconds
                )
        except Exception as exc:
            self.state = SystemState.CRITICAL
            self.state_reason = str(exc)
            self.database.open_alert(Severity.CRITICAL, "SENSOR_BUS", str(exc))
        self._poll_task = asyncio.create_task(self._poll_loop(), name="sensor-poll")
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(), name="spray-scheduler")
        self._maintenance_task = asyncio.create_task(self._maintenance_loop(), name="retention")
        await self.events.publish("system.state.changed", self.status().model_dump(mode="json"))

    async def _maintenance_loop(self) -> None:
        """Enforce the telemetry retention horizon so the SD card survives."""
        while not self._stopping:
            try:
                horizon = datetime.now(timezone.utc) - timedelta(
                    days=self.settings.retention_days
                )
                removed = await asyncio.to_thread(
                    self.database.prune_readings, horizon.isoformat()
                )
                if removed:
                    await self.events.publish("retention.pruned", {"rows": removed})
            except asyncio.CancelledError:
                raise
            except Exception:  # retention must never take the control plane down
                pass
            await asyncio.sleep(self.settings.retention_interval_seconds)

    async def stop(self) -> None:
        self._stopping = True
        self.state = SystemState.SHUTTING_DOWN
        for task in (self._poll_task, self._scheduler_task, self._maintenance_task, *self._tasks):
            if task:
                task.cancel()
        self.database.set_setting("automation_enabled", "0")
        self.next_spray_at = None
        await self.hardware.set_mist_pump(False)
        await self.hardware.set_dosing_pump(False)
        await self.hardware.set_mixer(False)
        await self.hardware.set_fan(False)
        await asyncio.gather(
            *(
                task
                for task in (
                    self._poll_task,
                    self._scheduler_task,
                    self._maintenance_task,
                    *self._tasks,
                )
                if task
            ),
            return_exceptions=True,
        )

    async def _read_sensors_bounded(self) -> SensorSnapshot:
        """Read sensors with a hard deadline.

        The Pi adapter does blocking I2C and 1-Wire work in a worker thread. A
        wedged bus would otherwise hang the poll loop forever with no exception,
        leaving the last snapshot on screen as though it were live.
        """
        try:
            return await asyncio.wait_for(
                self.hardware.read_sensors(), timeout=self.settings.sensor_timeout_seconds
            )
        except TimeoutError as exc:
            raise ControlError(
                f"sensor bus did not respond within {self.settings.sensor_timeout_seconds:g}s"
            ) from exc

    async def _poll_loop(self) -> None:
        while not self._stopping:
            try:
                snapshot = await self._read_sensors_bounded()
                self.latest = snapshot
                await asyncio.to_thread(self.database.add_reading, snapshot)
                if self.database.has_open_alert("SENSOR_BUS"):
                    self.database.resolve_alert("SENSOR_BUS")
                if self.development_session_expires_at and not self.development_session_active():
                    await self.disarm_development_session(expired=True)
                await self._update_fan_policy(snapshot)
                critical_open = any(
                    alert.severity == Severity.CRITICAL
                    for alert in self.database.alerts(open_only=True)
                )
                if not critical_open and self.state != SystemState.ACTIVE:
                    self._normal_state()
                await self.events.publish("sensor.updated", snapshot.model_dump(mode="json"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state = SystemState.CRITICAL
                self.state_reason = "Sensor bus unavailable"
                self.database.open_alert(Severity.CRITICAL, "SENSOR_BUS", str(exc))
                self.fan_requested = False
                await self.hardware.set_fan(False)
                await self.events.publish("system.state.changed", self.status().model_dump(mode="json"))
            await asyncio.sleep(2)

    async def _update_fan_policy(self, snapshot: SensorSnapshot) -> None:
        temperature = snapshot.air_temperature_c
        humidity = snapshot.relative_humidity_percent
        requested = self.fan_requested
        if temperature is None or humidity is None:
            self.fan_requested = False
            self._fan_request_changed_at = datetime.now(timezone.utc)
            await self.hardware.set_fan(False)
            return
        elif not requested and (temperature >= 28.0 or humidity >= 80.0):
            requested = True
        elif requested and temperature <= 26.0 and humidity <= 75.0:
            requested = False
        now = datetime.now(timezone.utc)
        if requested != self.fan_requested:
            # Hold the previous request through the debounce window, but still
            # re-assert it on the hardware below so the relay cannot drift.
            if (now - self._fan_request_changed_at).total_seconds() >= 60:
                self.fan_requested = requested
                self._fan_request_changed_at = now
        physical_request = (
            self.fan_requested and self.actuators_enabled and self.development_session_active()
        )
        await self.hardware.set_fan(physical_request)

    async def _scheduler_loop(self) -> None:
        while not self._stopping:
            now = datetime.now(timezone.utc)
            if (
                self.next_spray_at
                and now >= self.next_spray_at
                and self.database.get_setting("automation_enabled") == "1"
                and not self.hardware.mist_pump_active
                and self.actuators_enabled
                and (not self.missing_interlocks or self.development_session_active())
            ):
                duration = self.settings.spray_duration_seconds
                if self.missing_interlocks:
                    duration = min(duration, self.settings.development_mist_limit_seconds)
                try:
                    await self.request_mist(duration, "automatic recirculation schedule")
                except ControlError as exc:
                    self.next_spray_at = now + timedelta(
                        seconds=self.settings.spray_interval_seconds
                    )
                    await self.events.publish(
                        "automation.cycle.blocked",
                        {"reason": str(exc), "next_attempt_at": self.next_spray_at.isoformat()},
                    )
            await asyncio.sleep(1)

    async def set_automatic_recirculation(self, enabled: bool) -> None:
        """Enable or disable the local automatic mist-pump schedule.

        Missing level and flow interlocks are permitted only inside the bounded,
        supervised development session. Enabling this mode starts that session
        atomically so the UI toggle cannot leave automation armed without its
        expiry timer.
        """
        if not enabled:
            self.database.set_setting("automation_enabled", "0")
            self.next_spray_at = None
            await self.hardware.set_mist_pump(False)
            if self.development_session_active():
                await self.disarm_development_session()
            await self.events.publish("automation.changed", {"enabled": False})
            return

        self._validate_common_safety()
        if self.missing_interlocks and not self.development_session_active():
            await self.arm_development_session()
        self.database.set_setting("automation_enabled", "1")
        self.next_spray_at = datetime.now(timezone.utc) + timedelta(
            seconds=self.settings.spray_interval_seconds
        )
        await self.events.publish(
            "automation.changed",
            {
                "enabled": True,
                "next_spray_at": self.next_spray_at.isoformat(),
                "development_session_expires_at": (
                    self.development_session_expires_at.isoformat()
                    if self.development_session_expires_at
                    else None
                ),
            },
        )

    def status(self) -> SystemStatus:
        active = self.database.active_experiment()
        commissioned = self.database.get_setting("commissioned") == "1"
        state = self.state if commissioned else SystemState.COMMISSIONING
        expiry = (
            self.development_session_expires_at if self.development_session_active() else None
        )
        return SystemStatus(
            state=state,
            reason=self.state_reason,
            commissioned=commissioned,
            automation_enabled=self.database.get_setting("automation_enabled") == "1",
            simulator=self.settings.simulator,
            active_experiment=active["name"] if active else None,
            pump_active=self.hardware.mist_pump_active,
            dosing_active=self.hardware.dosing_pump_active,
            fan_requested=self.fan_requested,
            fan_active=self.hardware.fan_active,
            actuators_enabled=self.actuators_enabled,
            hardware_capabilities=self.hardware.capabilities,
            missing_interlocks=self.missing_interlocks,
            development_session_expires_at=expiry,
            next_spray_at=self.next_spray_at,
            last_successful_spray_at=self.last_successful_spray_at,
            open_alerts=len(self.database.alerts(open_only=True)),
            version=__version__,
        )

    def _validate_common_safety(self) -> None:
        if self.latest is None:
            raise ControlError("fresh sensor data is unavailable")
        level = self.latest.reservoir_percent
        if level is not None and level <= 5:
            raise ControlError("reservoir level is below the safe threshold")
        if self.state == SystemState.CRITICAL:
            raise ControlError("system is in critical safety lockout")
        if not self.actuators_enabled:
            raise ControlError("actuator master enable is off; outputs remain physically disabled")

    async def request_mist(self, duration: float, reason: str) -> CommandResult:
        self._validate_common_safety()
        hard_limit = self.settings.manual_spray_limit_seconds
        if self.missing_interlocks:
            if not self.development_session_active():
                raise ControlError("arm a supervised development session before requesting mist")
            hard_limit = min(hard_limit, self.settings.development_mist_limit_seconds)
        if duration > hard_limit:
            raise ControlError(f"requested mist duration exceeds the {hard_limit:g}-second hard limit")
        if self._actuator_lock.locked() or self._operation_pending:
            raise ControlError("another actuator operation is already active")
        command_id = str(uuid.uuid4())
        self.database.add_spray_event(command_id, duration, reason)
        self._operation_pending = True
        task = asyncio.create_task(self._run_mist(command_id, duration), name=f"mist-{command_id}")
        self._track(task)
        return CommandResult(accepted=True, command_id=command_id, message="Misting command accepted")

    async def _run_mist(self, command_id: str, duration: float) -> None:
        async with self._actuator_lock:
            self.state = SystemState.ACTIVE
            self.state_reason = "Misting cycle in progress"
            await self.hardware.set_mist_pump(True)
            await self.events.publish("spray.started", {"command_id": command_id, "duration": duration})
            try:
                await asyncio.sleep(min(0.35, duration))
                reading = await self.hardware.read_sensors()
                if (
                    reading.flow_lpm is not None
                    and reading.flow_lpm < self.settings.minimum_flow_lpm
                ):
                    raise ControlError("pump started but delivery flow was not confirmed")
                await asyncio.sleep(max(0, duration - 0.35))
                outcome = "completed" if reading.flow_lpm is not None else "completed_unverified"
                self.database.finish_spray_event(
                    command_id, flow=reading.flow_lpm, outcome=outcome
                )
                self.last_successful_spray_at = datetime.now(timezone.utc)
                self.next_spray_at = self.last_successful_spray_at + timedelta(
                    seconds=self.settings.spray_interval_seconds
                )
                self.database.resolve_alert("NO_FLOW")
                await self.events.publish(
                    "spray.completed",
                    {"command_id": command_id, "flow_lpm": reading.flow_lpm, "outcome": outcome},
                )
            except Exception as exc:
                self.database.finish_spray_event(command_id, flow=None, outcome="failed")
                self.database.open_alert(Severity.CRITICAL, "NO_FLOW", str(exc))
                self.state = SystemState.CRITICAL
                self.state_reason = str(exc)
                await self.events.publish("spray.failed", {"command_id": command_id, "reason": str(exc)})
            finally:
                await self.hardware.set_mist_pump(False)
                self._operation_pending = False
                if self.state != SystemState.CRITICAL:
                    self._normal_state()
                await self.events.publish("system.state.changed", self.status().model_dump(mode="json"))

    async def request_dose(self, volume_ml: float, reason: str) -> CommandResult:
        self._validate_common_safety()
        if not self.hardware.capabilities.nutrient_dosing or not self.hardware.capabilities.ec:
            raise ControlError("nutrient dosing and EC measurement are not commissioned")
        if self.latest is None or self.latest.ec_ms_cm is None:
            raise ControlError("EC measurement is unavailable")
        if self.latest.ec_ms_cm >= float(self.database.get_setting("ec_target") or "1.7"):
            raise ControlError("EC is already at or above the configured target")
        now = datetime.now(timezone.utc)
        hour_total = self.database.dose_total_since((now - timedelta(hours=1)).isoformat())
        day_total = self.database.dose_total_since((now - timedelta(hours=24)).isoformat())
        if hour_total + volume_ml > self.settings.dosing_hourly_limit_ml:
            raise ControlError("hourly nutrient dosing limit would be exceeded")
        if day_total + volume_ml > self.settings.dosing_daily_limit_ml:
            raise ControlError("daily nutrient dosing limit would be exceeded")
        if self._actuator_lock.locked() or self._operation_pending:
            raise ControlError("another actuator operation is already active")
        command_id = str(uuid.uuid4())
        self.database.add_dose_event(command_id, volume_ml, reason)
        self._operation_pending = True
        task = asyncio.create_task(self._run_dose(command_id, volume_ml), name=f"dose-{command_id}")
        self._track(task)
        return CommandResult(accepted=True, command_id=command_id, message="Nutrient pulse accepted")

    async def reset_safety_lockout(self) -> None:
        if self._actuator_lock.locked() or self._operation_pending:
            raise ControlError("cannot reset safety while an actuator operation is active")
        if self.hardware.mist_pump_active or self.hardware.dosing_pump_active:
            raise ControlError("cannot reset safety while an output is active")
        try:
            snapshot = await self._read_sensors_bounded()
        except Exception as exc:
            raise ControlError("sensor bus must recover before safety can be reset") from exc
        self.latest = snapshot
        self._validate_common_safety_snapshot(snapshot)
        for code in ("NO_FLOW", "DOSE_FAILED", "SENSOR_BUS"):
            self.database.resolve_alert(code)
        self._normal_state("Safety lockout reset by operator")
        await self.events.publish("system.state.changed", self.status().model_dump(mode="json"))

    @staticmethod
    def _validate_common_safety_snapshot(snapshot: SensorSnapshot) -> None:
        if snapshot.reservoir_percent is not None and snapshot.reservoir_percent <= 5:
            raise ControlError("reservoir level is below the safe threshold")

    async def _run_dose(self, command_id: str, volume_ml: float) -> None:
        async with self._actuator_lock:
            rate = float(self.database.get_setting("dose_calibration_ml_s") or "1")
            self.state = SystemState.ACTIVE
            self.state_reason = "Nutrient dosing in progress"
            await self.events.publish("dose.started", {"command_id": command_id, "volume_ml": volume_ml})
            try:
                await self.hardware.set_dosing_pump(True)
                await asyncio.sleep(volume_ml / rate)
                await self.hardware.set_dosing_pump(False)
                await self.hardware.set_mixer(True)
                await asyncio.sleep(2 if self.settings.simulator else 120)
                await self.hardware.set_mixer(False)
                self.database.finish_dose_event(command_id, "completed")
                await self.events.publish("dose.completed", {"command_id": command_id, "volume_ml": volume_ml})
            except Exception as exc:
                self.database.finish_dose_event(command_id, "failed")
                self.database.open_alert(Severity.CRITICAL, "DOSE_FAILED", str(exc))
                self.state = SystemState.CRITICAL
                self.state_reason = str(exc)
                await self.events.publish("dose.locked", {"command_id": command_id, "reason": str(exc)})
            finally:
                await self.hardware.set_dosing_pump(False)
                await self.hardware.set_mixer(False)
                self._operation_pending = False
                if self.state != SystemState.CRITICAL:
                    self._normal_state()
                await self.events.publish("system.state.changed", self.status().model_dump(mode="json"))

    def _track(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
