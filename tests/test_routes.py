"""Auth-boundary and static-serving regression tests.

The API is reachable from the kiosk network and can energize a pump, so which
routes are public is a safety property, not a detail. This module pins the
entire surface: a new route that is neither listed as public nor protected
fails the suite until somebody decides which it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeroos.main import client_is_local, create_app
from aeroos.settings import Settings

# Readable without a PIN. The kiosk renders these before anyone authenticates.
PUBLIC_ROUTES = {
    "/healthz",
    "/api/v1/auth/login",
    "/api/v1/status",
    "/api/v1/sensors/latest",
    "/api/v1/history",
    "/api/v1/statistics",
    "/api/v1/stream",
    "/api/v1/sprays",
    "/api/v1/alerts",
    "/api/v1/experiments",
    "/api/v1/captures",
    "/api/v1/captures/{capture_id}/image",
    "/api/v1/camera/live",
    "/api/v1/system/identity",
    "/api/v1/commission",
    "/{path:path}",
}

# Requires a valid session token.
PROTECTED_ROUTES = {
    "/api/v1/auth/logout",
    "/api/v1/alerts/{alert_id}/acknowledge",
    "/api/v1/experiments/start",
    "/api/v1/experiments/{experiment_id}/stop",
    "/api/v1/export/readings.csv",
    "/api/v1/simulator/fault/{fault}",
    "/api/v1/diagnostics/probe",
    "/api/v1/diagnostics/commands",
    "/api/v1/diagnostics/run/{name}",
    "/api/v1/diagnostics/actions",
    "/api/v1/network/status",
    "/api/v1/network/scan",
    "/api/v1/hardware/pins",
    "/api/v1/ai/status",
    "/api/v1/ai/diagnose",
    "/api/v1/ai/explain",
    "/api/v1/ai/ask",
    "/api/v1/ai/captures/{capture_id}",
    "/api/v1/ai/briefing",
    "/api/v1/ai/growth-plan",
    "/api/v1/ai/experiments/{experiment_id}/report",
}

# Requires a PIN entered inside the elevation window: anything that can move an
# actuator, arm automation, or clear a safety lockout.
ELEVATED_ROUTES = {
    "/api/v1/mist",
    "/api/v1/dose",
    "/api/v1/automation/{enabled}",
    "/api/v1/safety/reset",
    "/api/v1/development-session/arm",
    "/api/v1/development-session/disarm",
    "/api/v1/network/connect",
    "/api/v1/network/disconnect",
    "/api/v1/network/forget",
    "/api/v1/network/lan-exposure/{enabled}",
    "/api/v1/ai/enabled/{enabled}",
}

DOCS_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def make_settings(path: Path, *, elevation_seconds: int = 300) -> Settings:
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
        elevation_seconds=elevation_seconds,
    )


def test_every_route_has_a_declared_trust_level(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    declared = PUBLIC_ROUTES | PROTECTED_ROUTES | ELEVATED_ROUTES | DOCS_ROUTES
    actual = {route.path for route in app.routes if hasattr(route, "path")}
    actual -= {"/assets"}
    undeclared = actual - declared
    assert not undeclared, (
        f"New route(s) {sorted(undeclared)} must be added to PUBLIC_ROUTES, "
        "PROTECTED_ROUTES, or ELEVATED_ROUTES in this file."
    )


def test_protected_routes_reject_anonymous_callers(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/diagnostics/probe").status_code == 401
        assert client.get("/api/v1/diagnostics/commands").status_code == 401
        assert client.post("/api/v1/diagnostics/run/i2c-scan").status_code == 401
        assert client.get("/api/v1/diagnostics/actions").status_code == 401
        assert client.get("/api/v1/export/readings.csv").status_code == 401
        assert client.post("/api/v1/mist", json={"duration_seconds": 1, "reason": "test"}).status_code == 401
        assert client.post("/api/v1/safety/reset").status_code == 401


def test_actuator_routes_require_fresh_elevation(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, elevation_seconds=0))
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/login", json={"pin": "0420"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        # The session is valid, so reads still work…
        assert client.get("/api/v1/diagnostics/commands", headers=headers).status_code == 200
        # …but the elevation window has already lapsed.
        blocked = client.post(
            "/api/v1/mist", json={"duration_seconds": 1, "reason": "stale session"}, headers=headers
        )
        assert blocked.status_code == 403
        assert "PIN" in blocked.json()["detail"]


def test_logout_revokes_the_session(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/login", json={"pin": "0420"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/diagnostics/commands", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).json()["revoked"] is True
        assert client.get("/api/v1/diagnostics/commands", headers=headers).status_code == 401


def test_repeated_bad_pins_are_throttled(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        codes = [client.post("/api/v1/auth/login", json={"pin": "9999"}).status_code for _ in range(6)]
        assert codes[0] == 401
        assert 429 in codes, "brute-force attempts must eventually be locked out"
        locked = client.post("/api/v1/auth/login", json={"pin": "0420"})
        assert locked.status_code == 429
        assert "Retry-After" in locked.headers


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e%2f%2e%2e%2fpyproject.toml",
        "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/hosts",
        "/../../pyproject.toml",
        "/..%2f..%2fpyproject.toml",
    ],
)
def test_static_fallback_cannot_escape_the_bundle(tmp_path: Path, path: str) -> None:
    """Regression for the unauthenticated arbitrary-file-read in the SPA fallback."""
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert "[build-system]" not in response.text
        assert "hatchling" not in response.text
        assert "localhost" not in response.text.lower() or "<!doctype html" in response.text.lower()


def test_only_the_kiosk_counts_as_a_local_client() -> None:
    """First-boot commissioning is gated on this predicate."""
    from starlette.datastructures import Address

    class FakeRequest:
        def __init__(self, host: str | None) -> None:
            self.client = Address(host=host, port=1234) if host else None

    assert client_is_local(FakeRequest("127.0.0.1"))
    assert client_is_local(FakeRequest("::1"))
    assert not client_is_local(FakeRequest("192.168.1.50"))
    assert not client_is_local(FakeRequest("10.0.0.9"))
    assert not client_is_local(FakeRequest(None))


def test_commissioned_appliance_requires_elevation_to_rewrite_the_pin(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        # The simulator boots commissioned, so this route is now PIN-gated.
        response = client.post(
            "/api/v1/commission",
            json={"chamber_name": "Takeover", "operator_pin": "1234"},
        )
        assert response.status_code == 401
