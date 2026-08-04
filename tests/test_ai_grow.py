"""Grow-side AI: briefings, growth plans, run reports, root assessments.

These features put a language model next to a machine that drives a pump, so the
properties worth pinning are not "does it answer" — the simulator always answers
— but: the answer is stored where the research record can find it, reading it
back never spends quota, and nothing the model returns reaches the controller.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from aeroos.database import Database
from aeroos.main import create_app
from aeroos.settings import Settings


def make_settings(path: Path) -> Settings:
    return Settings(
        data_dir=path,
        simulator=True,
        operator_pin="0420",
        spray_duration_seconds=0.2,
        spray_interval_seconds=300,
        manual_spray_limit_seconds=10,
        minimum_flow_lpm=0.2,
        dosing_pulse_ml=1,
        dosing_hourly_limit_ml=5,
        dosing_daily_limit_ml=20,
    )


def authorize(client: TestClient) -> dict[str, str]:
    token = client.post("/api/v1/auth/login", json={"pin": "0420"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/ai/enabled/true", headers=headers)
    return headers


def test_reading_the_briefing_does_not_generate_one(tmp_path: Path) -> None:
    """The home screen renders constantly; only an explicit press spends quota."""
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        first = client.get("/api/v1/ai/briefing", headers=headers)
        assert first.status_code == 200
        assert first.json() == {"answer": "", "generated_at": None, "stale": True}


def test_briefing_is_generated_once_and_read_back_from_storage(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        created = client.post("/api/v1/ai/briefing", headers=headers)
        assert created.status_code == 200
        body = created.json()
        assert body["stale"] is False and body["generated_at"]
        assert "[simulator]" in body["answer"]

        cached = client.get("/api/v1/ai/briefing", headers=headers).json()
        assert cached["answer"] == body["answer"]
        assert cached["generated_at"] == body["generated_at"]
        assert cached["stale"] is False


def test_growth_plan_is_advice_and_changes_no_setting(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        before = client.get("/api/v1/status").json()
        response = client.post(
            "/api/v1/ai/growth-plan",
            headers=headers,
            json={"stage": "vegetative", "goal": "faster root development"},
        )
        assert response.status_code == 200
        body = response.json()
        # The contract the UI relies on: the chamber did not adopt anything.
        assert body["applied"] is False
        assert body["crop"] == "Mint"
        after = client.get("/api/v1/status").json()
        assert after["automation_enabled"] == before["automation_enabled"]
        assert after["actuators_enabled"] == before["actuators_enabled"]
        assert after["next_spray_at"] == before["next_spray_at"]


def test_growth_plan_without_a_crop_is_refused(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = authorize(client)
        active = client.get("/api/v1/experiments").json()[0]
        client.post(f"/api/v1/experiments/{active['id']}/stop", headers=headers)
        response = client.post("/api/v1/ai/growth-plan", headers=headers, json={})
        assert response.status_code == 409
        assert "crop" in response.json()["detail"]


def test_experiment_report_is_written_to_the_experiment_record(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        experiment = client.get("/api/v1/experiments").json()[0]
        response = client.post(
            f"/api/v1/ai/experiments/{experiment['id']}/report", headers=headers
        )
        assert response.status_code == 200
        answer = response.json()["answer"]
        assert response.json()["experiment"]["ai_report"] == answer
        # Survives the request: a report only in the browser is not a record.
        stored = client.get("/api/v1/experiments").json()[0]
        assert stored["ai_report"] == answer
        assert stored["ai_report_at"]


def test_report_for_an_unknown_experiment_is_a_404(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        assert client.post("/api/v1/ai/experiments/999/report", headers=headers).status_code == 404


def test_root_assessment_is_stored_against_the_capture(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = authorize(client)
        capture = client.post("/api/v1/captures", headers=headers).json()
        response = client.post(f"/api/v1/ai/captures/{capture['id']}", headers=headers)
        assert response.status_code == 200
        answer = response.json()["answer"]
        stored = next(
            item for item in client.get("/api/v1/captures").json() if item["id"] == capture["id"]
        )
        assert stored["ai_assessment"] == answer
        assert stored["ai_assessed_at"]


def test_grow_endpoints_reject_anonymous_callers(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/v1/ai/briefing").status_code == 401
        assert client.post("/api/v1/ai/briefing").status_code == 401
        assert client.post("/api/v1/ai/growth-plan", json={}).status_code == 401
        assert client.post("/api/v1/ai/experiments/1/report").status_code == 401


def test_disabled_assistant_refuses_every_grow_surface(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        token = client.post("/api/v1/auth/login", json={"pin": "0420"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        # AI is off by default because these calls leave the appliance.
        assert client.post("/api/v1/ai/briefing", headers=headers).status_code == 503
        assert client.post("/api/v1/ai/growth-plan", headers=headers, json={}).status_code == 503


def test_migration_adds_assessment_columns_to_an_existing_database(tmp_path: Path) -> None:
    """Appliances are already flashed; a v2 data partition must carry forward."""
    path = tmp_path / "aeroos.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, captured_at TEXT NOT NULL,
            image_path TEXT NOT NULL, root_area_px INTEGER NOT NULL, quality TEXT NOT NULL
        );
        CREATE TABLE experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, crop TEXT NOT NULL,
            notes TEXT NOT NULL, state TEXT NOT NULL, started_at TEXT, ended_at TEXT
        );
        INSERT INTO settings VALUES ('schema_version', '2', '2026-01-01T00:00:00+00:00');
        INSERT INTO captures(captured_at,image_path,root_area_px,quality)
            VALUES ('2026-01-01T00:00:00+00:00', '/tmp/a.png', 1200, 'good');
        """
    )
    legacy.commit()
    legacy.close()

    database = Database(path)
    try:
        assert database.migrate() == Database.SCHEMA_VERSION
        record = database.capture(1)
        assert record is not None
        # The pre-existing row survived and gained the new field as empty.
        assert record["root_area_px"] == 1200
        assert record["ai_assessment"] is None
        assert database.set_capture_assessment(1, "looks healthy")["ai_assessment"] == "looks healthy"
    finally:
        database.close()
