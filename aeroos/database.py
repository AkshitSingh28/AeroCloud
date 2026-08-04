from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Alert, SensorSnapshot, Severity
from .security import hash_pin


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA foreign_keys=ON")

    def initialize(self, *, simulator: bool, operator_pin: str) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sensor_timestamp ON sensor_readings(timestamp);
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            severity TEXT NOT NULL,
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            acknowledged_at TEXT,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS spray_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL UNIQUE,
            requested_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds REAL NOT NULL,
            measured_flow_lpm REAL,
            reason TEXT NOT NULL,
            outcome TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dose_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id TEXT NOT NULL UNIQUE,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            volume_ml REAL NOT NULL,
            reason TEXT NOT NULL,
            outcome TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            crop TEXT NOT NULL,
            notes TEXT NOT NULL,
            state TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            image_path TEXT NOT NULL,
            root_area_px INTEGER NOT NULL,
            quality TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_log_timestamp ON action_log(timestamp);
        """
        with self._lock:
            self._connection.executescript(schema)
            self._connection.commit()
        self.migrate()
        defaults = {
            "commissioned": "1" if simulator else "0",
            "automation_enabled": "1" if simulator else "0",
            "chamber_name": "Research chamber A1",
            "operator_pin_hash": hash_pin(operator_pin),
            "ec_target": "1.7",
            "ec_deadband": "0.1",
            "dose_calibration_ml_s": "1.0",
            "reservoir_volume_l": "15",
        }
        for key, value in defaults.items():
            if self.get_setting(key) is None:
                self.set_setting(key, value)
        if simulator and not self.active_experiment():
            self.start_experiment("Mint growth trial", "Mint", "Simulator-seeded research run")

    # ------------------------------------------------------------- migrations

    SCHEMA_VERSION = 3

    def migrate(self) -> int:
        """Bring an existing data partition up to the current schema.

        Appliances are already flashed and running, so every schema change from
        here needs a forward path that does not lose field data. Each step is
        idempotent and runs inside one transaction.
        """
        current = int(self.get_setting("schema_version") or "1")
        if current >= self.SCHEMA_VERSION:
            if self.get_setting("schema_version") is None:
                self.set_setting("schema_version", str(self.SCHEMA_VERSION))
            return current
        with self._lock:
            if current < 2:
                # v2 promotes the queryable sensor fields out of the JSON blob so
                # analytics can aggregate in SQL instead of loading every row.
                columns = {
                    row["name"] for row in self._connection.execute("PRAGMA table_info(sensor_readings)")
                }
                for column in (
                    "air_temperature_c",
                    "relative_humidity_percent",
                    "solution_temperature_c",
                    "light_percent",
                    "ph",
                    "ec_ms_cm",
                    "reservoir_percent",
                    "flow_lpm",
                ):
                    if column not in columns:
                        self._connection.execute(
                            f"ALTER TABLE sensor_readings ADD COLUMN {column} REAL"
                        )
                        self._connection.execute(
                            f"UPDATE sensor_readings SET {column} = "
                            f"json_extract(payload, '$.{column}') WHERE {column} IS NULL"
                        )
            if current < 3:
                # v3 keeps AI assessments with the record they describe. A root
                # assessment written next to the capture is part of the research
                # trail; one that lives in a browser tab is gone at the next
                # reload and cannot be defended in a write-up.
                for table, column in (
                    ("captures", "ai_assessment TEXT"),
                    ("captures", "ai_assessed_at TEXT"),
                    ("experiments", "ai_report TEXT"),
                    ("experiments", "ai_report_at TEXT"),
                ):
                    existing = {
                        row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")
                    }
                    if column.split()[0] not in existing:
                        self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            self._connection.commit()
        self.set_setting("schema_version", str(self.SCHEMA_VERSION))
        return self.SCHEMA_VERSION

    def close(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._connection.close()

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, _iso_now()),
            )
            self._connection.commit()

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def add_reading(self, snapshot: SensorSnapshot) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO sensor_readings("
                "timestamp,payload,air_temperature_c,relative_humidity_percent,"
                "solution_temperature_c,light_percent,ph,ec_ms_cm,reservoir_percent,flow_lpm"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot.timestamp.isoformat(),
                    snapshot.model_dump_json(),
                    snapshot.air_temperature_c,
                    snapshot.relative_humidity_percent,
                    snapshot.solution_temperature_c,
                    snapshot.light_percent,
                    snapshot.ph,
                    snapshot.ec_ms_cm,
                    snapshot.reservoir_percent,
                    snapshot.flow_lpm,
                ),
            )
            self._connection.commit()

    def statistics(self, since_iso: str, until_iso: str | None = None) -> dict[str, Any]:
        """Server-side aggregation over the promoted columns.

        The optional upper bound lets a caller aggregate a closed window — an
        experiment that has already ended, or the 24 hours before the current
        ones when the question is which direction the chamber is moving.
        """
        query = (
            "SELECT COUNT(*) samples,"
            " AVG(air_temperature_c) avg_air_temperature_c,"
            " MIN(air_temperature_c) min_air_temperature_c,"
            " MAX(air_temperature_c) max_air_temperature_c,"
            " AVG(relative_humidity_percent) avg_relative_humidity_percent,"
            " MIN(relative_humidity_percent) min_relative_humidity_percent,"
            " MAX(relative_humidity_percent) max_relative_humidity_percent,"
            " AVG(solution_temperature_c) avg_solution_temperature_c,"
            " AVG(light_percent) avg_light_percent,"
            " AVG(ec_ms_cm) avg_ec_ms_cm,"
            " AVG(ph) avg_ph"
            " FROM sensor_readings WHERE timestamp>=?"
        )
        params: list[Any] = [since_iso]
        if until_iso:
            query += " AND timestamp<?"
            params.append(until_iso)
        with self._lock:
            row = self._connection.execute(query, params).fetchone()
        return {key: row[key] for key in row.keys()}

    def delivery_summary(self, since_iso: str, until_iso: str | None = None) -> dict[str, Any]:
        """Spray and dose totals for a window, used for run reports and briefings."""
        bound = " AND requested_at<?" if until_iso else ""
        params: list[Any] = [since_iso] + ([until_iso] if until_iso else [])
        with self._lock:
            spray = self._connection.execute(
                "SELECT COUNT(*) sprays,"
                " COALESCE(SUM(duration_seconds),0) spray_seconds,"
                " COALESCE(SUM(outcome='failed'),0) spray_failures,"
                " AVG(measured_flow_lpm) avg_flow_lpm"
                f" FROM spray_events WHERE requested_at>=?{bound}",
                params,
            ).fetchone()
            dose = self._connection.execute(
                "SELECT COUNT(*) doses, COALESCE(SUM(volume_ml),0) dose_ml"
                f" FROM dose_events WHERE requested_at>=?{bound}",
                params,
            ).fetchone()
        return {**{key: spray[key] for key in spray.keys()}, **{key: dose[key] for key in dose.keys()}}

    def prune_readings(self, before_iso: str) -> int:
        """Delete raw telemetry older than the retention horizon.

        Sensor rows land every two seconds — roughly 43,000 per day — on an SD
        card that has to survive years of field use.
        """
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM sensor_readings WHERE timestamp<?", (before_iso,)
            )
            self._connection.commit()
            return cursor.rowcount

    def has_open_alert(self, code: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM alerts WHERE code=? AND resolved_at IS NULL LIMIT 1", (code,)
            ).fetchone()
        return row is not None

    def recent_actions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def readings(self, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM sensor_readings ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def open_alert(self, severity: Severity, code: str, message: str) -> int:
        with self._lock:
            existing = self._connection.execute(
                "SELECT id FROM alerts WHERE code=? AND resolved_at IS NULL", (code,)
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = self._connection.execute(
                "INSERT INTO alerts(severity,code,message,opened_at) VALUES(?,?,?,?)",
                (severity.value, code, message, _iso_now()),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def resolve_alert(self, code: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE alerts SET resolved_at=? WHERE code=? AND resolved_at IS NULL", (_iso_now(), code)
            )
            self._connection.commit()

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE alerts SET acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL",
                (_iso_now(), alert_id),
            )
            self._connection.commit()
            return cursor.rowcount == 1

    def alerts(self, *, open_only: bool = False) -> list[Alert]:
        query = "SELECT * FROM alerts"
        if open_only:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY id DESC"
        with self._lock:
            rows = self._connection.execute(query).fetchall()
        return [Alert(**dict(row)) for row in rows]

    def add_spray_event(
        self, command_id: str, duration: float, reason: str, outcome: str = "accepted"
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO spray_events(command_id,requested_at,duration_seconds,reason,outcome) VALUES(?,?,?,?,?)",
                (command_id, _iso_now(), duration, reason, outcome),
            )
            self._connection.commit()

    def finish_spray_event(self, command_id: str, *, flow: float | None, outcome: str) -> None:
        now = _iso_now()
        with self._lock:
            self._connection.execute(
                "UPDATE spray_events SET started_at=COALESCE(started_at,requested_at), completed_at=?, "
                "measured_flow_lpm=?, outcome=? WHERE command_id=?",
                (now, flow, outcome, command_id),
            )
            self._connection.commit()

    def recent_sprays(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM spray_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_dose_event(self, command_id: str, volume: float, reason: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO dose_events(command_id,requested_at,volume_ml,reason,outcome) VALUES(?,?,?,?,?)",
                (command_id, _iso_now(), volume, reason, "accepted"),
            )
            self._connection.commit()

    def finish_dose_event(self, command_id: str, outcome: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE dose_events SET completed_at=?, outcome=? WHERE command_id=?",
                (_iso_now(), outcome, command_id),
            )
            self._connection.commit()

    def dose_total_since(self, iso_timestamp: str) -> float:
        with self._lock:
            # A dose that failed mid-delivery still put nutrient in the reservoir,
            # so it counts against the limit. Only a dose that never started is free.
            row = self._connection.execute(
                "SELECT COALESCE(SUM(volume_ml),0) total FROM dose_events "
                "WHERE requested_at>=? AND outcome IN ('accepted','completed','failed')",
                (iso_timestamp,),
            ).fetchone()
        return float(row["total"])

    def start_experiment(self, name: str, crop: str, notes: str) -> dict[str, Any]:
        current = self.active_experiment()
        if current:
            raise ValueError("an experiment is already active")
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO experiments(name,crop,notes,state,started_at) VALUES(?,?,?,?,?)",
                (name, crop, notes, "active", _iso_now()),
            )
            self._connection.commit()
            experiment_id = int(cursor.lastrowid)
        return self.experiment(experiment_id)

    def stop_experiment(self, experiment_id: int) -> dict[str, Any]:
        with self._lock:
            self._connection.execute(
                "UPDATE experiments SET state='completed', ended_at=? WHERE id=? AND state='active'",
                (_iso_now(), experiment_id),
            )
            self._connection.commit()
        return self.experiment(experiment_id)

    def experiment(self, experiment_id: int) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return dict(row)

    def active_experiment(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM experiments WHERE state='active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def add_capture(self, image_path: str, root_area_px: int, quality: str) -> dict[str, Any]:
        now = _iso_now()
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO captures(captured_at,image_path,root_area_px,quality) VALUES(?,?,?,?)",
                (now, image_path, root_area_px, quality),
            )
            self._connection.commit()
            capture_id = int(cursor.lastrowid)
            row = self._connection.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
        return dict(row)

    def capture(self, capture_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM captures WHERE id=?", (capture_id,)
            ).fetchone()
        return dict(row) if row else None

    def captures(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM captures ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def captures_between(self, since_iso: str, until_iso: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM captures WHERE captured_at>=?"
        params: list[Any] = [since_iso]
        if until_iso:
            query += " AND captured_at<?"
            params.append(until_iso)
        query += " ORDER BY captured_at ASC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def set_capture_assessment(self, capture_id: int, assessment: str) -> dict[str, Any] | None:
        """Attach an AI root assessment to the capture it describes."""
        with self._lock:
            self._connection.execute(
                "UPDATE captures SET ai_assessment=?, ai_assessed_at=? WHERE id=?",
                (assessment, _iso_now(), capture_id),
            )
            self._connection.commit()
        return self.capture(capture_id)

    def set_experiment_report(self, experiment_id: int, report: str) -> dict[str, Any]:
        with self._lock:
            self._connection.execute(
                "UPDATE experiments SET ai_report=?, ai_report_at=? WHERE id=?",
                (report, _iso_now(), experiment_id),
            )
            self._connection.commit()
        return self.experiment(experiment_id)

    def audit(self, actor: str, action: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO action_log(timestamp,actor,action,payload) VALUES(?,?,?,?)",
                (_iso_now(), actor, action, json.dumps(payload, separators=(",", ":"))),
            )
            self._connection.commit()
