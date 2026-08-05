<div align="center">

<img src="branding/aeroos-mark.svg" alt="AeroOS" width="88">

# AeroOS

**A research appliance for aeroponics.**

Climate, misting, root imaging, and reproducible experiments — on one
Raspberry Pi, with no cloud and no internet requirement.

[Documentation](docs/) · [Hardware](#hardware) · [Architecture](#architecture) · [Safety](#safety)

</div>

---

AeroOS turns a Raspberry Pi 4 into a dedicated instrument for growing plants in
mist. It owns the sensors and the actuators, records every reading locally,
photographs the root zone, and binds the whole run to a named experiment.

It is designed around a single assumption: **this machine can flood a room.** A
pump under software control, in a sealed chamber, with a reservoir attached, is
a device that fails wet. Most of what follows is a consequence of taking that
seriously.

---

## Principles

**Outputs do not exist until commissioned.** With the actuator master enable
off, the GPIO output objects are never constructed — not guarded by a branch,
not created.

**A measurement it cannot take reads null.** AeroOS does not substitute a
plausible number for a sensor that is absent, and says so in the interface.

**Presence is proven, not assumed.** Physical controls require a PIN entered
within the last five minutes. A kiosk session open for weeks is not evidence
that anyone is standing at the machine.

**Nothing survives a reboot.** On restart the controller takes fresh readings
and decides again rather than resuming a command it can no longer justify.

---

## The appliance

### Operations

A touch-first shell that boots straight into fullscreen. Live climate and
solution telemetry, mist scheduling with a countdown, the delivery path from
reservoir to nozzle to return drain, and the current safety state — always
visible, never more than one tap away.

### Bring-up

A diagnostics workspace for the hours spent wiring. Every measurement the
control plane expects, its live value, and whether it is healthy, silent, or
simply not connected yet; a fixed registry of read-only checks that show their
exact invocation before they run; an audit trail of every command and every
refusal.

There is deliberately no arbitrary shell. A service that can energize a pump
does not also get a general command endpoint.

### Research

Experiments bind telemetry, mist events, doses, and root captures to a named
run. Root area is measured over time from the camera, and readings export for
analysis elsewhere.

### Assistance — optional, off by default

Gemini, reading the chamber's own data: a briefing on the last day of
operation, a growth plan for the crop and stage in progress, an assessment
written onto a root capture, a report written onto a finished run, and an ask
box in every workspace. Prompts carry the capability map, so the assistant
knows which measurements this appliance actually has.

Two properties are structural rather than policy. The assistant is
**advisory** — there is no code path from a model response to a control call.
And it is **opt-in**, because every request sends chamber data off the
appliance. Every call is audited.

### Network

The API listens on loopback, so only the touchscreen reaches it. Publishing it
on the LAN is a deliberate, warned, off-by-default choice. WiFi is provisioned
from the touchscreen, and GPIO assignments are editable from the interface —
with reserved lines refused and relay lines immovable while outputs are live.

---

## Hardware

| Component | Interface | Purpose |
|---|---|---|
| Raspberry Pi 4 | — | Controller |
| SC1227 7" touchscreen | DSI | 800×480 kiosk |
| DHT22 | BCM18 | Chamber temperature and humidity |
| DS18B20 | BCM4 (1-Wire) | Solution temperature |
| TEMT6000 + PCF8591 | I²C `0x48` | Coarse ambient light |
| Arducam B0483 | CSI | Root imaging — 1080p15 live, 9152×6944 stills |
| Mist relay | BCM17 | Pump — disabled until commissioned |
| Fan relay | BCM25 | Circulation — disabled until commissioned |

pH, EC, flow, and reservoir level are not commissioned. AeroOS does not pretend
an 8-bit ADC is a chemistry instrument; those fields stay null.

---

## Architecture

```
Raspberry Pi 4
├── aeroos-camera-gate.service    verifies the sensor before anything else starts
├── aeroos.service                control plane — forces outputs off, then opens
│   ├── AeroController            state machine, polling, safety interlocks
│   ├── Hardware                  one contract, two adapters: Pi and simulator
│   ├── Database                  SQLite WAL — telemetry, experiments, audit
│   ├── VisionService             live stream and still capture
│   ├── DiagnosticsService        allow-listed probes and commands
│   └── FastAPI                   local REST and SSE, loopback by default
└── aeroos-kiosk.service          Cage and Chromium, started last
```

The interface talks only to the local API. It never touches GPIO or the
database directly.

Safety states run `commissioning` → `safe` → `active` → `degraded` →
`critical` → `maintenance` → `shutting_down`. Actuator requests are refused in
`critical` until an operator clears the lockout deliberately.

---

## Documentation

| | |
|---|---|
| [Getting started](docs/GETTING_STARTED.md) | Running the simulator, building an image, configuring assistance |
| [Commissioning manual](docs/AeroOS_Hardware_Setup_and_Commissioning_Manual.pdf) | Illustrated build and wiring sequence |
| [Bring-up contract](docs/HARDWARE.md) | Pin assignments and commissioning state |
| [Architecture](docs/ARCHITECTURE.md) | Control plane internals |
| [Validation](docs/VALIDATION.md) | Gates before physical actuation |

The appliance runs fully in simulation, including assistance, so the entire
system can be evaluated before any hardware exists.

---

## Safety

Physical misting and dosing remain disabled until flow, level, pump delivery,
power recovery, and emergency behaviour are calibrated and validated on the
assembled rig. The simulator's defaults are development aids, not crop or
chemical recommendations.

Neither AeroOS nor its assistant is a substitute for knowing what you are
putting in the water.

---

## License

MIT — see [LICENSE](LICENSE).
