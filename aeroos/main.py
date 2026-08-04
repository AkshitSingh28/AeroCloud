from __future__ import annotations

import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .control import AeroController, ControlError
from .database import Database
from .hardware import Hardware, SimulatorHardware
from .models import (
    AIAskRequest,
    AIDiagnoseRequest,
    AIExplainRequest,
    AIGrowthPlanRequest,
    CommissioningRequest,
    DoseRequest,
    ExperimentRequest,
    LoginRequest,
    PinAssignmentRequest,
    SprayRequest,
    SystemState,
    WifiConnectRequest,
    WifiForgetRequest,
)
from .ai import AIUnavailable, GeminiService, load_keys
from .diagnostics import DiagnosticsService
from .hardware_config import (
    MAX_GPIO,
    MIN_GPIO,
    RESERVED_GPIO,
    HardwareProfile,
    PinValidationError,
    pin_catalog,
    update_pins,
)
from .network import NetworkError, NetworkService
from .security import LoginThrottle, SessionStore, hash_pin, verify_pin
from .settings import Settings, load_settings
from .vision import VisionService


LOCAL_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def client_is_local(request: Request) -> bool:
    """True when the caller is the kiosk browser on this appliance."""
    return bool(request.client) and request.client.host in LOCAL_CLIENTS


def create_app(settings: Settings | None = None, hardware: Hardware | None = None) -> FastAPI:
    settings = settings or load_settings()
    database = Database(settings.database_path)
    database.initialize(simulator=settings.simulator, operator_pin=settings.operator_pin)
    if hardware is None:
        if settings.simulator:
            hardware = SimulatorHardware()
        else:
            from .pi_hardware import RaspberryPiHardware

            hardware = RaspberryPiHardware(
                settings.hardware_config_path,
                actuators_enabled=settings.actuators_enabled,
            )
    controller = AeroController(settings, database, hardware)
    vision = VisionService(settings.data_dir / "images", simulator=settings.simulator)
    sessions = SessionStore(elevation_seconds=settings.elevation_seconds)
    throttle = LoginThrottle()
    diagnostics = DiagnosticsService(
        simulator=settings.simulator,
        hardware_profile=getattr(hardware, "profile", None),
        extra_commands_path=settings.diagnostics_extra_path,
        camera_gate_dir=settings.camera_gate_dir,
    )
    network = NetworkService(simulator=settings.simulator, interface=settings.wifi_interface)
    assistant = GeminiService(
        keys=load_keys(settings.gemini_env_path),
        model=settings.gemini_model,
        enabled=database.get_setting("ai_enabled") == "1",
        simulator=settings.simulator,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await controller.start()
        try:
            yield
        finally:
            await asyncio.to_thread(vision.close)
            await controller.stop()
            database.close()

    app = FastAPI(
        title="AeroOS API",
        version="0.1.0",
        description="Local control and research API for AeroOS",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.controller = controller
    app.state.hardware = hardware

    def _bearer(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="operator authentication required")
        return authorization.removeprefix("Bearer ").strip()

    def require_operator(authorization: Annotated[str | None, Header()] = None) -> str:
        token = _bearer(authorization)
        if not sessions.valid(token):
            raise HTTPException(status_code=401, detail="operator session expired")
        return "operator"

    def require_elevated_operator(authorization: Annotated[str | None, Header()] = None) -> str:
        """Guard for anything that can move an actuator or change safety state.

        A kiosk browser tab lives for days, so a session token alone is not
        evidence that the operator is still standing at the appliance. These
        routes need a PIN entered inside the elevation window.
        """
        token = _bearer(authorization)
        if not sessions.valid(token):
            raise HTTPException(status_code=401, detail="operator session expired")
        if not sessions.elevated(token):
            raise HTTPException(
                status_code=403, detail="re-enter the operator PIN to confirm this command"
            )
        return "operator"

    def operator_or_commissioning(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> str:
        # An uncommissioned appliance has no PIN yet, so first-boot setup cannot
        # require one. It is restricted to the local kiosk instead — otherwise
        # whoever reaches the port first on the network owns the appliance.
        if database.get_setting("commissioned") != "1":
            if not client_is_local(request):
                raise HTTPException(
                    status_code=403,
                    detail="commissioning must be completed on the appliance touchscreen",
                )
            return "local-commissioning"
        return require_elevated_operator(authorization)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "aeroos-api"}

    @app.post("/api/v1/auth/login")
    async def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
        client = request.client.host if request.client else "unknown"
        retry_after = throttle.retry_after(client)
        if retry_after > 0:
            database.audit("anonymous", "auth.login.throttled", {"retry_after": round(retry_after)})
            raise HTTPException(
                status_code=429,
                detail=f"too many failed attempts; retry in {round(retry_after)}s",
                headers={"Retry-After": str(round(retry_after))},
            )
        encoded = database.get_setting("operator_pin_hash") or ""
        if not encoded or not verify_pin(payload.pin, encoded):
            delay = throttle.record_failure(client)
            database.audit("anonymous", "auth.login.failed", {"lockout_seconds": round(delay)})
            raise HTTPException(status_code=401, detail="invalid operator PIN")
        throttle.record_success(client)
        token = sessions.create()
        database.audit("operator", "auth.login", {})
        return {
            "token": token,
            "expires_in_seconds": 28800,
            "elevated_for_seconds": settings.elevation_seconds,
        }

    @app.post("/api/v1/auth/logout")
    async def logout(authorization: Annotated[str | None, Header()] = None) -> dict[str, bool]:
        token = _bearer(authorization)
        revoked = sessions.revoke(token)
        database.audit("operator", "auth.logout", {})
        return {"revoked": revoked}

    @app.get("/api/v1/status")
    async def status() -> dict[str, Any]:
        return controller.status().model_dump(mode="json")

    @app.get("/api/v1/sensors/latest")
    async def latest_sensors() -> dict[str, Any]:
        if controller.latest is None:
            raise HTTPException(status_code=503, detail="sensor data unavailable")
        return controller.latest.model_dump(mode="json")

    @app.get("/api/v1/history")
    async def history(limit: int = Query(default=120, ge=1, le=2000)) -> list[dict[str, Any]]:
        return database.readings(limit)

    @app.get("/api/v1/stream")
    async def stream(request: Request) -> StreamingResponse:
        async def events():
            async with controller.events.subscribe() as queue:
                yield "event: connected\ndata: {}\n\n"
                while not await request.is_disconnected():
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: {item['type']}\ndata: {json.dumps(item)}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v1/mist")
    async def mist(payload: SprayRequest, actor: str = Depends(require_elevated_operator)) -> dict[str, Any]:
        try:
            result = await controller.request_mist(payload.duration_seconds, payload.reason)
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "mist.requested", payload.model_dump())
        return result.model_dump()

    @app.post("/api/v1/development-session/arm")
    async def arm_development_session(actor: str = Depends(require_elevated_operator)) -> dict[str, Any]:
        try:
            expires_at = await controller.arm_development_session()
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "development-session.armed", {"expires_at": expires_at.isoformat()})
        return {"armed": True, "expires_at": expires_at.isoformat()}

    @app.post("/api/v1/development-session/disarm")
    async def disarm_development_session(actor: str = Depends(require_elevated_operator)) -> dict[str, bool]:
        await controller.disarm_development_session()
        database.audit(actor, "development-session.disarmed", {})
        return {"armed": False}

    @app.get("/api/v1/sprays")
    async def sprays() -> list[dict[str, Any]]:
        return database.recent_sprays()

    @app.post("/api/v1/dose")
    async def dose(payload: DoseRequest, actor: str = Depends(require_elevated_operator)) -> dict[str, Any]:
        try:
            result = await controller.request_dose(payload.volume_ml, payload.reason)
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "dose.requested", payload.model_dump())
        return result.model_dump()

    @app.get("/api/v1/alerts")
    async def alerts(open_only: bool = False) -> list[dict[str, Any]]:
        return [alert.model_dump(mode="json") for alert in database.alerts(open_only=open_only)]

    @app.post("/api/v1/alerts/{alert_id}/acknowledge")
    async def acknowledge_alert(alert_id: int, actor: str = Depends(require_operator)) -> dict[str, bool]:
        acknowledged = database.acknowledge_alert(alert_id)
        database.audit(actor, "alert.acknowledged", {"alert_id": alert_id})
        return {"acknowledged": acknowledged}

    @app.get("/api/v1/experiments")
    async def experiments() -> list[dict[str, Any]]:
        return database.experiments()

    @app.post("/api/v1/experiments/start")
    async def start_experiment(
        payload: ExperimentRequest, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        try:
            experiment = database.start_experiment(payload.name, payload.crop, payload.notes)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "experiment.started", experiment)
        await controller.events.publish("experiment.changed", experiment)
        return experiment

    @app.post("/api/v1/experiments/{experiment_id}/stop")
    async def stop_experiment(
        experiment_id: int, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        try:
            experiment = database.stop_experiment(experiment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="experiment not found") from exc
        database.audit(actor, "experiment.stopped", experiment)
        await controller.events.publish("experiment.changed", experiment)
        return experiment

    @app.post("/api/v1/captures")
    async def capture(actor: str = Depends(require_operator)) -> dict[str, Any]:
        try:
            image_path, root_area, quality = await vision.capture_and_analyze()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        record = database.add_capture(image_path, root_area, quality)
        database.audit(actor, "capture.completed", record)
        await controller.events.publish("capture.completed", record)
        return record

    @app.get("/api/v1/captures")
    async def captures() -> list[dict[str, Any]]:
        return database.captures()

    @app.get("/api/v1/captures/{capture_id}/image")
    async def capture_image(capture_id: int) -> FileResponse:
        record = database.capture(capture_id)
        if record is None:
            raise HTTPException(status_code=404, detail="capture not found")
        return FileResponse(record["image_path"])

    @app.get("/api/v1/camera/live")
    async def live_camera() -> Response:
        headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}
        if settings.simulator:
            return Response(
                content=vision.simulator_live_svg(),
                media_type="image/svg+xml",
                headers=headers,
            )
        return StreamingResponse(
            vision.mjpeg_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers=headers,
        )

    @app.post("/api/v1/commission")
    async def commission(
        payload: CommissioningRequest, actor: str = Depends(operator_or_commissioning)
    ) -> dict[str, bool]:
        database.set_setting("chamber_name", payload.chamber_name)
        database.set_setting("operator_pin_hash", hash_pin(payload.operator_pin))
        database.set_setting("commissioned", "1")
        database.audit(actor, "system.commissioned", {"chamber_name": payload.chamber_name})
        return {"commissioned": True}

    @app.post("/api/v1/automation/{enabled}")
    async def automation(enabled: bool, actor: str = Depends(require_elevated_operator)) -> dict[str, Any]:
        try:
            await controller.set_automatic_recirculation(enabled)
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status = controller.status()
        database.audit(
            actor,
            "automation.changed",
            {
                "enabled": status.automation_enabled,
                "next_spray_at": (
                    status.next_spray_at.isoformat() if status.next_spray_at else None
                ),
                "development_session_expires_at": (
                    status.development_session_expires_at.isoformat()
                    if status.development_session_expires_at
                    else None
                ),
            },
        )
        return {
            "enabled": status.automation_enabled,
            "next_spray_at": (
                status.next_spray_at.isoformat() if status.next_spray_at else None
            ),
            "development_session_expires_at": (
                status.development_session_expires_at.isoformat()
                if status.development_session_expires_at
                else None
            ),
        }

    @app.post("/api/v1/safety/reset")
    async def reset_safety(actor: str = Depends(require_elevated_operator)) -> dict[str, bool]:
        try:
            await controller.reset_safety_lockout()
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "safety.lockout.reset", {})
        return {"reset": True}

    @app.get("/api/v1/system/identity")
    async def identity() -> dict[str, Any]:
        return {
            "product": "AeroOS",
            "edition": "Research Preview",
            "version": "0.1.0",
            "hostname": "aeroos.local",
            "hardware": "Raspberry Pi 4" if not settings.simulator else "AeroOS Simulator",
            "kernel": "host-simulator" if settings.simulator else "raspberrypi-linux",
            "chamber_name": database.get_setting("chamber_name"),
        }

    @app.get("/api/v1/diagnostics/probe")
    async def diagnostics_probe(actor: str = Depends(require_operator)) -> dict[str, Any]:
        """Per-sensor bring-up state with wiring expectations and fault hints."""
        results = await asyncio.to_thread(
            diagnostics.probe,
            controller.latest,
            hardware.capabilities,
            actuators_enabled=controller.actuators_enabled,
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "simulator": settings.simulator,
            "summary": diagnostics.summary(results),
            "probes": [result.as_dict() for result in results],
        }

    @app.get("/api/v1/diagnostics/commands")
    async def diagnostics_commands(actor: str = Depends(require_operator)) -> list[dict[str, Any]]:
        return diagnostics.commands()

    @app.post("/api/v1/diagnostics/run/{name}")
    async def diagnostics_run(
        name: str, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        try:
            result = await diagnostics.run(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown diagnostic command") from exc
        database.audit(actor, "diagnostics.run", {"command": name, "exit_code": result["exit_code"]})
        return result

    @app.get("/api/v1/diagnostics/actions")
    async def diagnostics_actions(
        limit: int = Query(default=100, ge=1, le=500), actor: str = Depends(require_operator)
    ) -> list[dict[str, Any]]:
        """Recent audit trail — every operator command and every rejection."""
        return database.recent_actions(limit)

    # ----------------------------------------------------------------- network

    @app.get("/api/v1/network/status")
    async def network_status(actor: str = Depends(require_operator)) -> dict[str, Any]:
        state = await network.status()
        state["api_on_lan"] = database.get_setting("api_bind_lan") == "1"
        state["api_bind_host"] = settings.bind_host
        return state

    @app.post("/api/v1/network/scan")
    async def network_scan(actor: str = Depends(require_operator)) -> list[dict[str, Any]]:
        try:
            return await network.scan()
        except NetworkError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/v1/network/connect")
    async def network_connect(
        payload: WifiConnectRequest, actor: str = Depends(require_elevated_operator)
    ) -> dict[str, Any]:
        try:
            result = await network.connect(payload.ssid, payload.passphrase)
        except NetworkError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # The passphrase belongs to iwd, not to the AeroOS audit trail.
        database.audit(actor, "network.connected", {"ssid": payload.ssid})
        return result

    @app.post("/api/v1/network/disconnect")
    async def network_disconnect(actor: str = Depends(require_elevated_operator)) -> dict[str, Any]:
        try:
            result = await network.disconnect()
        except NetworkError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "network.disconnected", {})
        return result

    @app.post("/api/v1/network/forget")
    async def network_forget(
        payload: WifiForgetRequest, actor: str = Depends(require_elevated_operator)
    ) -> dict[str, Any]:
        try:
            result = await network.forget(payload.ssid)
        except NetworkError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        database.audit(actor, "network.forgotten", {"ssid": payload.ssid})
        return result

    @app.post("/api/v1/network/lan-exposure/{enabled}")
    async def network_lan_exposure(
        enabled: bool, actor: str = Depends(require_elevated_operator)
    ) -> dict[str, Any]:
        """Publish the control API beyond loopback.

        This moves the appliance from 'only the kiosk can reach it' to 'anyone on
        the WiFi can reach it'. It takes effect on the next service restart, and
        the operator is told exactly that.
        """
        database.set_setting("api_bind_lan", "1" if enabled else "0")
        database.audit(actor, "network.lan_exposure", {"enabled": enabled})
        return {
            "enabled": enabled,
            "active": settings.bind_host not in {"127.0.0.1", "::1"},
            "restart_required": True,
            "restart_command": "sudo systemctl restart aeroos",
        }

    # ---------------------------------------------------------------- pin edits

    @app.get("/api/v1/hardware/pins")
    async def hardware_pins(actor: str = Depends(require_operator)) -> dict[str, Any]:
        profile = getattr(hardware, "profile", None) or HardwareProfile()
        return {
            "pins": pin_catalog(profile),
            "reserved": [{"gpio": gpio, "reason": reason} for gpio, reason in sorted(RESERVED_GPIO.items())],
            "range": {"min": MIN_GPIO, "max": MAX_GPIO},
            "editable": settings.hardware_config_path is not None and not settings.simulator,
            "config_path": str(settings.hardware_config_path or ""),
            "actuators_enabled": controller.actuators_enabled,
        }

    @app.put("/api/v1/hardware/pins")
    async def update_hardware_pins(
        payload: PinAssignmentRequest, actor: str = Depends(require_elevated_operator)
    ) -> dict[str, Any]:
        assignments = payload.assignments()
        if not assignments:
            raise HTTPException(status_code=422, detail="no pin changes were supplied")
        # Reassigning a line mid-operation would leave a relay driven by a GPIO
        # object the control plane no longer believes it owns.
        if controller.state == SystemState.ACTIVE or hardware.mist_pump_active or hardware.dosing_pump_active:
            raise HTTPException(
                status_code=409, detail="cannot change pins while an actuator operation is active"
            )
        if controller.actuators_enabled and any(
            field in assignments for field in ("mist_gpio", "fan_gpio")
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "disable the actuator master enable before reassigning a relay line, so the "
                    "old GPIO is released in a known-safe state"
                ),
            )
        if settings.simulator or settings.hardware_config_path is None:
            raise HTTPException(
                status_code=503,
                detail="pin editing requires a physical appliance with /etc/aeroos/hardware.toml",
            )
        try:
            warnings = update_pins(settings.hardware_config_path, assignments)
        except PinValidationError as exc:
            raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
        except (OSError, FileNotFoundError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not write the hardware profile: {exc}. Is /etc/aeroos writable?",
            ) from exc
        database.audit(actor, "hardware.pins.updated", assignments)
        await controller.events.publish("hardware.pins.updated", {"assignments": assignments})
        return {
            "updated": assignments,
            "warnings": warnings,
            "restart_required": True,
            "restart_command": "sudo systemctl restart aeroos",
        }

    # --------------------------------------------------------------- assistant

    @app.get("/api/v1/ai/status")
    async def ai_status(actor: str = Depends(require_operator)) -> dict[str, Any]:
        return assistant.status()

    @app.post("/api/v1/ai/enabled/{enabled}")
    async def ai_enabled(
        enabled: bool, actor: str = Depends(require_elevated_operator)
    ) -> dict[str, Any]:
        assistant.enabled = enabled
        database.set_setting("ai_enabled", "1" if enabled else "0")
        database.audit(actor, "ai.enabled", {"enabled": enabled})
        return assistant.status()

    @app.post("/api/v1/ai/diagnose")
    async def ai_diagnose(
        payload: AIDiagnoseRequest, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        probes = await asyncio.to_thread(
            diagnostics.probe,
            controller.latest,
            hardware.capabilities,
            actuators_enabled=controller.actuators_enabled,
        )
        status_now = controller.status()
        context = {
            "state": status_now.state.value,
            "reason": status_now.reason,
            "simulator": settings.simulator,
            "probes": [
                result.as_dict()
                for result in probes
                if payload.include_healthy or result.state in {"missing", "degraded", "unknown"}
            ],
            "alerts": [alert.model_dump(mode="json") for alert in database.alerts(open_only=True)],
            "console": payload.console_output,
        }
        try:
            answer = await assistant.diagnose(context)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        database.audit(actor, "ai.diagnose", {"probes": len(context["probes"])})
        return {"answer": answer, "probes_considered": len(context["probes"])}

    @app.post("/api/v1/ai/explain")
    async def ai_explain(
        payload: AIExplainRequest, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        try:
            answer = await assistant.explain_error(payload.subject, payload.detail, payload.context)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        database.audit(actor, "ai.explain", {"subject": payload.subject})
        return {"answer": answer}

    @app.post("/api/v1/ai/ask")
    async def ai_ask(payload: AIAskRequest, actor: str = Depends(require_operator)) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        context = {
            "chamber": database.get_setting("chamber_name"),
            "experiment": database.active_experiment(),
            "status": controller.status().model_dump(mode="json"),
            "sensors": controller.latest.model_dump(mode="json") if controller.latest else {},
            "statistics": database.statistics(since.isoformat()),
            "alerts": [alert.model_dump(mode="json") for alert in database.alerts()][:10],
        }
        try:
            answer = await assistant.ask(payload.question, context, scope=payload.scope)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        database.audit(actor, "ai.ask", {"question": payload.question[:120], "scope": payload.scope})
        return {"answer": answer}

    # ------------------------------------------------------- grow intelligence

    def _run_day(experiment: dict[str, Any] | None) -> int | None:
        """How far into the run we are, for stage-aware advice."""
        if not experiment or not experiment.get("started_at"):
            return None
        started = datetime.fromisoformat(experiment["started_at"])
        return max(1, (datetime.now(timezone.utc) - started).days + 1)

    def _grow_context(hours: int = 24) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        previous = since - timedelta(hours=hours)
        status_now = controller.status()
        experiment = database.active_experiment()
        return {
            "chamber": database.get_setting("chamber_name"),
            "state": status_now.state.value,
            "reason": status_now.reason,
            "experiment": (experiment or {}) | {"day": _run_day(experiment)},
            # The capability map is what stops the model advising on pH the
            # chamber cannot measure. It travels with every grow prompt.
            "capabilities": status_now.hardware_capabilities.model_dump(),
            "sensors": controller.latest.model_dump(mode="json") if controller.latest else {},
            "window": database.statistics(since.isoformat()),
            "previous": database.statistics(previous.isoformat(), since.isoformat()),
            "delivery": database.delivery_summary(since.isoformat()),
            "captures": [
                {k: v for k, v in item.items() if k in {"captured_at", "root_area_px", "quality"}}
                for item in database.captures_between(since.isoformat())
            ][-12:],
            "alerts": [
                alert.model_dump(mode="json") for alert in database.alerts(open_only=True)
            ],
        }

    @app.get("/api/v1/ai/briefing")
    async def ai_briefing_cached(actor: str = Depends(require_operator)) -> dict[str, Any]:
        """The last generated briefing. Reading it never calls the model.

        The home screen renders on every kiosk wake-up. If that regenerated the
        briefing it would burn the free-tier quota on nobody looking at it.
        """
        generated_at = database.get_setting("ai_briefing_at")
        stale = True
        if generated_at:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(generated_at)
            stale = age > timedelta(hours=6)
        return {
            "answer": database.get_setting("ai_briefing") or "",
            "generated_at": generated_at,
            "stale": stale,
        }

    @app.post("/api/v1/ai/briefing")
    async def ai_briefing(actor: str = Depends(require_operator)) -> dict[str, Any]:
        try:
            answer = await assistant.briefing(_grow_context())
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        generated_at = datetime.now(timezone.utc).isoformat()
        database.set_setting("ai_briefing", answer)
        database.set_setting("ai_briefing_at", generated_at)
        database.audit(actor, "ai.briefing", {})
        return {"answer": answer, "generated_at": generated_at, "stale": False}

    @app.post("/api/v1/ai/growth-plan")
    async def ai_growth_plan(
        payload: AIGrowthPlanRequest, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        context = _grow_context()
        experiment = context["experiment"]
        crop = payload.crop or experiment.get("crop")
        if not crop:
            raise HTTPException(
                status_code=409,
                detail="start an experiment or name a crop before asking for a growth plan",
            )
        context |= {
            "crop": crop,
            "stage": payload.stage,
            "goal": payload.goal,
            "day": experiment.get("day"),
            "profile": {
                "mist_seconds": settings.spray_duration_seconds,
                "interval_seconds": settings.spray_interval_seconds,
                "automation_enabled": controller.status().automation_enabled,
                "actuators_enabled": controller.actuators_enabled,
            },
        }
        try:
            answer = await assistant.growth_plan(context)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        database.audit(actor, "ai.growth_plan", {"crop": crop, "stage": payload.stage})
        # Advice, not configuration: the controller is not told about any of it.
        return {"answer": answer, "crop": crop, "stage": payload.stage, "applied": False}

    @app.post("/api/v1/ai/experiments/{experiment_id}/report")
    async def ai_experiment_report(
        experiment_id: int, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        try:
            experiment = database.experiment(experiment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="experiment not found") from exc
        if not experiment.get("started_at"):
            raise HTTPException(status_code=409, detail="this experiment has not started")
        start = experiment["started_at"]
        end = experiment.get("ended_at")
        status_now = controller.status()
        context = {
            "experiment": experiment | {"day": _run_day(experiment)},
            "capabilities": status_now.hardware_capabilities.model_dump(),
            "window": database.statistics(start, end),
            "delivery": database.delivery_summary(start, end),
            "captures": [
                {k: v for k, v in item.items() if k in {"captured_at", "root_area_px", "quality"}}
                for item in database.captures_between(start, end)
            ],
            "alerts": [
                alert.model_dump(mode="json")
                for alert in database.alerts()
                if alert.opened_at.isoformat() >= start
            ][:20],
        }
        try:
            answer = await assistant.experiment_report(context)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # Written to the experiment row: a summary that vanishes with the browser
        # tab is not part of the research record.
        record = database.set_experiment_report(experiment_id, answer)
        database.audit(actor, "ai.experiment.report", {"experiment_id": experiment_id})
        return {"answer": answer, "experiment": record}

    @app.post("/api/v1/ai/captures/{capture_id}")
    async def ai_analyze_capture(
        capture_id: int, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        record = database.capture(capture_id)
        if record is None:
            raise HTTPException(status_code=404, detail="capture not found")
        path = Path(record["image_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="capture image is missing from storage")
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        if path.suffix.lower() == ".svg":
            # Simulator captures are vector placeholders, not photographs.
            image = b""
            mime = "image/svg+xml"
        else:
            image = await asyncio.to_thread(path.read_bytes)
        # Give the model the growth context it cannot see in a single frame.
        earlier = [
            item for item in database.captures() if item["id"] < capture_id
        ][:1]
        notes = f"Measured root area: {record['root_area_px']} px."
        if earlier:
            notes += (
                f" Previous capture {earlier[0]['captured_at']} measured "
                f"{earlier[0]['root_area_px']} px."
            )
        experiment = database.active_experiment()
        if experiment:
            notes += f" Crop: {experiment['crop']}, day {_run_day(experiment)} of the run."
        try:
            answer = await assistant.analyze_capture(image, mime, notes=notes)
        except AIUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        stored = database.set_capture_assessment(capture_id, answer)
        database.audit(actor, "ai.capture.analyzed", {"capture_id": capture_id})
        return {"answer": answer, "capture_id": capture_id, "capture": stored}

    @app.get("/api/v1/statistics")
    async def statistics(hours: int = Query(default=24, ge=1, le=720)) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return {"hours": hours, "since": since.isoformat(), **database.statistics(since.isoformat())}

    @app.get("/api/v1/export/readings.csv")
    async def export_readings(actor: str = Depends(require_operator)) -> StreamingResponse:
        rows = database.readings(2000)
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        database.audit(actor, "readings.exported", {"rows": len(rows)})
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=aeroos-readings.csv"},
        )

    @app.post("/api/v1/simulator/fault/{fault}")
    async def simulator_fault(
        fault: str, enabled: bool = True, actor: str = Depends(require_operator)
    ) -> dict[str, Any]:
        if not isinstance(hardware, SimulatorHardware):
            raise HTTPException(status_code=404, detail="simulator controls unavailable")
        if fault == "flow":
            hardware.flow_fault = enabled
        elif fault == "sensor":
            hardware.sensor_fault = enabled
        elif fault == "reservoir":
            hardware.reservoir_percent = 2 if enabled else 72
        else:
            raise HTTPException(status_code=404, detail="unknown simulator fault")
        database.audit(actor, "simulator.fault", {"fault": fault, "enabled": enabled})
        return {"fault": fault, "enabled": enabled}

    ui_dist = Path(__file__).resolve().parent.parent / "ui" / "dist"
    if ui_dist.exists():
        ui_root = ui_dist.resolve()
        assets = ui_root / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def ui_fallback(path: str) -> FileResponse:
            # The URL path is attacker-controlled and percent-decoded before it
            # reaches here, so it must be resolved and confined to the bundle
            # directory. Without this, '%2e%2e/%2e%2e/…' reads any file the
            # service user can open, including the database with the PIN hash.
            index = ui_root / "index.html"
            if not path:
                return FileResponse(index)
            candidate = (ui_root / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(ui_root):
                return FileResponse(candidate)
            return FileResponse(index)
    else:
        @app.get("/", include_in_schema=False)
        async def ui_missing() -> HTMLResponse:
            return HTMLResponse("<h1>AeroOS API</h1><p>Build the UI with <code>npm run build</code>.</p>")

    return app


app = create_app()


def run() -> None:
    """Entry point used by the systemd unit.

    The bind address comes from the operator's stored choice, so turning LAN
    access on or off is a setting plus a service restart rather than an edit to
    a unit file.
    """
    settings = load_settings()
    host = settings.bind_host
    database = Database(settings.database_path)
    try:
        if database.get_setting("api_bind_lan") == "1" and host in {"127.0.0.1", "::1"}:
            host = "0.0.0.0"
    finally:
        database.close()
    uvicorn.run("aeroos.main:app", host=host, port=settings.bind_port, reload=False)
