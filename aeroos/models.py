from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemState(StrEnum):
    COMMISSIONING = "commissioning"
    STARTING = "starting"
    SAFE = "safe"
    ACTIVE = "active"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"
    SHUTTING_DOWN = "shutting_down"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SensorSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    air_temperature_c: float | None = None
    relative_humidity_percent: float | None = None
    light_lux: float | None = None
    light_percent: float | None = None
    solution_temperature_c: float | None = None
    ph: float | None = None
    ec_ms_cm: float | None = None
    reservoir_percent: float | None = None
    flow_lpm: float | None = None
    power_voltage: float | None = None
    battery_percent: float | None = None


class HardwareCapabilities(BaseModel):
    climate: bool = False
    solution_temperature: bool = False
    light: bool = False
    camera: bool = False
    reservoir_level: bool = False
    flow: bool = False
    ph: bool = False
    ec: bool = False
    mist_output: bool = False
    fan_output: bool = False
    nutrient_dosing: bool = False
    mixer: bool = False


class SystemStatus(BaseModel):
    state: SystemState
    reason: str
    commissioned: bool
    automation_enabled: bool
    simulator: bool
    active_experiment: str | None
    pump_active: bool
    dosing_active: bool
    fan_requested: bool = False
    fan_active: bool = False
    actuators_enabled: bool = False
    hardware_capabilities: HardwareCapabilities = Field(default_factory=HardwareCapabilities)
    missing_interlocks: list[str] = Field(default_factory=list)
    development_session_expires_at: datetime | None = None
    next_spray_at: datetime | None
    last_successful_spray_at: datetime | None
    open_alerts: int
    version: str
    timestamp: datetime = Field(default_factory=utc_now)


class Alert(BaseModel):
    id: int
    severity: Severity
    code: str
    message: str
    opened_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


class SprayRequest(BaseModel):
    duration_seconds: float = Field(default=5, gt=0, le=10)
    reason: str = Field(default="operator request", min_length=3, max_length=160)


class DoseRequest(BaseModel):
    volume_ml: float = Field(default=1, gt=0, le=5)
    reason: str = Field(default="operator request", min_length=3, max_length=160)


class ExperimentRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    crop: str = Field(default="Mint", min_length=2, max_length=80)
    notes: str = Field(default="", max_length=500)


class CommissioningRequest(BaseModel):
    chamber_name: str = Field(default="Research chamber A1", min_length=2, max_length=80)
    operator_pin: str = Field(pattern=r"^\d{4,8}$")


class LoginRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{4,8}$")


class WifiConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    # Optional so open networks can be joined. Never persisted or audited.
    passphrase: str | None = Field(default=None, min_length=8, max_length=63)


class WifiForgetRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)


class PinAssignmentRequest(BaseModel):
    dht22_gpio: int | None = Field(default=None, ge=0, le=27)
    ds18b20_gpio: int | None = Field(default=None, ge=0, le=27)
    mist_gpio: int | None = Field(default=None, ge=0, le=27)
    fan_gpio: int | None = Field(default=None, ge=0, le=27)

    def assignments(self) -> dict[str, int]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class AIDiagnoseRequest(BaseModel):
    console_output: str = Field(default="", max_length=20000)
    include_healthy: bool = False


class AIExplainRequest(BaseModel):
    subject: str = Field(min_length=2, max_length=200)
    detail: str = Field(min_length=2, max_length=4000)
    context: str = Field(default="", max_length=20000)


class AIAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    # "hardware" frames the answer for bring-up; the default frames it for the
    # grow workspaces. It only selects a system brief — it grants nothing.
    scope: str = Field(default="chamber", pattern=r"^(chamber|hardware)$")


class AIGrowthPlanRequest(BaseModel):
    """Advisory target envelope. Nothing here is applied to the controller."""

    crop: str | None = Field(default=None, min_length=2, max_length=80)
    stage: str = Field(default="vegetative", min_length=2, max_length=40)
    goal: str = Field(default="", max_length=300)


class CommandResult(BaseModel):
    accepted: bool
    command_id: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
