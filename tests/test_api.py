from pathlib import Path

from fastapi.testclient import TestClient

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


def test_status_and_authenticated_command(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        status = client.get("/api/v1/status")
        assert status.status_code == 200
        assert status.json()["simulator"] is True
        assert client.post("/api/v1/mist", json={"duration_seconds": 1, "reason": "test"}).status_code == 401
        login = client.post("/api/v1/auth/login", json={"pin": "0420"})
        assert login.status_code == 200
        token = login.json()["token"]
        mist = client.post(
            "/api/v1/mist",
            json={"duration_seconds": 0.2, "reason": "API test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert mist.status_code == 200
        assert mist.json()["accepted"] is True

        automatic_off = client.post(
            "/api/v1/automation/false",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert automatic_off.status_code == 200
        assert automatic_off.json()["enabled"] is False

        automatic_on = client.post(
            "/api/v1/automation/true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert automatic_on.status_code == 200
        assert automatic_on.json()["enabled"] is True
        assert automatic_on.json()["next_spray_at"] is not None


def test_simulator_exposes_animated_live_camera_feed(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/v1/camera/live")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
        assert "AeroOS live simulator feed" in response.text
        assert "<animate" in response.text
