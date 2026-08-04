from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    simulator: bool
    operator_pin: str
    spray_duration_seconds: float
    spray_interval_seconds: float
    manual_spray_limit_seconds: float
    minimum_flow_lpm: float
    dosing_pulse_ml: float
    dosing_hourly_limit_ml: float
    dosing_daily_limit_ml: float
    hardware_config_path: Path | None = None
    actuators_enabled: bool = True
    development_session_minutes: int = 30
    development_mist_limit_seconds: float = 2.0
    sensor_timeout_seconds: float = 5.0
    retention_days: int = 30
    retention_interval_seconds: float = 3600.0
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080
    elevation_seconds: int = 300
    diagnostics_extra_path: Path | None = None
    camera_gate_dir: Path = Path("/var/lib/aeroos/camera-gate")
    gemini_env_path: Path | None = None
    gemini_model: str = "gemini-3.6-flash"
    wifi_interface: str = "wlan0"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aeroos.db"


def load_settings() -> Settings:
    simulator = os.getenv("AEROOS_SIMULATOR", "1") == "1"
    hardware_config = Path(os.getenv("AEROOS_HARDWARE_CONFIG", "/etc/aeroos/hardware.toml"))
    return Settings(
        data_dir=Path(os.getenv("AEROOS_DATA_DIR", "data")).resolve(),
        simulator=simulator,
        operator_pin=os.getenv("AEROOS_OPERATOR_PIN", "0420"),
        spray_duration_seconds=float(os.getenv("AEROOS_SPRAY_DURATION", "5")),
        spray_interval_seconds=float(os.getenv("AEROOS_SPRAY_INTERVAL", "300")),
        manual_spray_limit_seconds=float(os.getenv("AEROOS_MANUAL_SPRAY_LIMIT", "10")),
        minimum_flow_lpm=float(os.getenv("AEROOS_MINIMUM_FLOW_LPM", "0.2")),
        dosing_pulse_ml=float(os.getenv("AEROOS_DOSING_PULSE_ML", "1")),
        dosing_hourly_limit_ml=float(os.getenv("AEROOS_DOSING_HOURLY_LIMIT_ML", "5")),
        dosing_daily_limit_ml=float(os.getenv("AEROOS_DOSING_DAILY_LIMIT_ML", "20")),
        hardware_config_path=hardware_config,
        actuators_enabled=(
            os.getenv("AEROOS_ACTUATOR_MASTER_ENABLE", "1" if simulator else "0") == "1"
        ),
        development_session_minutes=int(os.getenv("AEROOS_DEVELOPMENT_SESSION_MINUTES", "30")),
        development_mist_limit_seconds=float(os.getenv("AEROOS_DEVELOPMENT_MIST_LIMIT", "2")),
        sensor_timeout_seconds=float(os.getenv("AEROOS_SENSOR_TIMEOUT", "5")),
        retention_days=int(os.getenv("AEROOS_RETENTION_DAYS", "30")),
        retention_interval_seconds=float(os.getenv("AEROOS_RETENTION_INTERVAL", "3600")),
        # The kiosk connects over loopback. Binding every interface is opt-in and
        # should only be enabled behind a trusted network boundary.
        bind_host=os.getenv("AEROOS_BIND_HOST", "127.0.0.1"),
        bind_port=int(os.getenv("AEROOS_BIND_PORT", "8080")),
        elevation_seconds=int(os.getenv("AEROOS_ELEVATION_SECONDS", "300")),
        diagnostics_extra_path=Path(
            os.getenv("AEROOS_DIAGNOSTICS_EXTRA", "/etc/aeroos/diagnostics.toml")
        ),
        camera_gate_dir=Path(os.getenv("AEROOS_CAMERA_GATE_DIR", "/var/lib/aeroos/camera-gate")),
        gemini_env_path=Path(os.getenv("AEROOS_GEMINI_ENV", "/etc/aeroos/gemini.env")),
        gemini_model=os.getenv("AEROOS_GEMINI_MODEL", "gemini-3.6-flash"),
        wifi_interface=os.getenv("AEROOS_WIFI_INTERFACE", "wlan0"),
    )
