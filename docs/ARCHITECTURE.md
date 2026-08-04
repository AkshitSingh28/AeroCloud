# AeroOS architecture

## Boot and process boundary

1. Raspberry Pi firmware loads the official kernel and device tree.
2. Linux mounts the system and AeroOS data filesystems.
3. `aeroos-camera-gate.service` verifies B0483 enumeration, streaming, autofocus, and still capture.
4. `aeroos.service` forces outputs off, opens SQLite, reads independent sensor adapters, and publishes capabilities.
5. `aeroos-kiosk.service` starts Cage and Chromium only after the control service is running.
6. The interface reads local REST/SSE data; it never accesses GPIO or SQLite directly.

The physical bring-up profile has actuator master enable off. Missing level, flow, pH and EC measurements are nullable capabilities, not fabricated values. Future supervised output sessions are PIN-protected, expire after 30 minutes, and cap misting at two seconds while interlocks are missing.

## Runtime components

- `AeroController`: state machine, polling, session expiry, fan dry-run policy, bounded controls, and event publishing.
- `Hardware`: common contract implemented by deterministic simulator and Raspberry Pi adapters.
- `Database`: SQLite WAL persistence for telemetry, experiments, alerts, sprays, doses, captures, settings, and audit events.
- `VisionService`: simulated SVG or B0483 1080p15 streaming and requested 64 MP still capture.
- `DiagnosticsService`: allow-listed read-only commands and per-sensor bring-up probes.
- FastAPI: versioned local REST API, operator sessions, CSV export, image access, and server-sent events.
- React shell: branded boot, operations, chamber, nutrients, vision, experiments, analytics, hardware, diagnostics, and settings workspaces.

## Access boundary

The API binds loopback by default; the kiosk is its only client. Telemetry is
readable unauthenticated on the appliance, session-scoped routes need a valid
operator token, and anything that can move an actuator needs a PIN entered
inside a five-minute elevation window. First-boot commissioning has no PIN to
check yet, so it is restricted to a local client instead.

The diagnostics console executes a fixed registry of argv vectors with a hard
timeout and never invokes a shell. The control plane can energize a pump, so an
arbitrary command endpoint is out of scope by design; appliance-specific checks
are declared in `/etc/aeroos/diagnostics.toml`, which is part of the image
rather than network input.

## Data durability

Sensor rows land every two seconds on an SD card. Queryable fields are stored in
real columns alongside the JSON payload so aggregation happens in SQL, a
retention loop prunes raw telemetry past the configured horizon, and schema
changes go through a numbered migration ladder because appliances are already
flashed and running in the field. The ladder is at v3: v2 promoted the queryable
sensor fields out of the JSON blob, v3 added the AI assessment columns to
`captures` and `experiments`.

## Safety states

- `commissioning`: no physical automatic output is permitted.
- `safe`: sensors and required interlocks are available.
- `active`: one serialized actuator operation is in progress.
- `degraded`: monitoring remains available but a non-critical capability is unavailable.
- `critical`: actuator requests are blocked until the fault is resolved.
- `maintenance`: automatic control is intentionally suspended.
- `shutting_down`: outputs are off while storage is flushed.

On reboot, AeroOS never repeats the last pump or dosing command. It obtains fresh readings and recalculates the next action.

## Optional subsystems

- `NetworkService`: iwd-backed WiFi provisioning. Credentials are passed on
  stdin and owned by iwd; AeroOS stores none of them.
- `GeminiService`: opt-in assistance over a rotating pool of API keys. Two
  framings share one transport: a hardware brief for bring-up (fault
  explanation, appliance diagnosis) and a grower brief for the product surfaces
  (chamber briefing, growth plan, run report, root assessment, chamber
  questions). Both are advisory by construction — no response can reach a
  control call — and this is the only component that sends data off the
  appliance. Every grow prompt carries the capability map so the model is told
  which measurements exist rather than inferring them.
  Assessments are written to the row they describe: a root read on the capture,
  a run summary on the experiment. Advice that lives only in a browser tab is
  not part of the research record.
- `hardware_config.update_pins`: validated GPIO reassignment written back to
  `/etc/aeroos/hardware.toml`. Reserved lines, duplicate assignments, and edits
  during an armed actuator state are refused.
