# Revision 2.0 validation gates

## Software

- Python unit, API and security tests pass.
- Production UI and Vitest suite pass.
- Nullable sensor fields remain `null`; pH, EC, reservoir and flow are never simulated in physical mode.
- Mist and dosing requests are rejected while actuator master enable is false.
- A supervised session cannot be armed until the master enable is commissioned.
- The development mist cap is two seconds when level or flow interlocks are unavailable.
- Fan hysteresis requests on at 28 deg C or 80% RH and off at 26 deg C and 75% RH.
- A stale or failed DHT22 reading requests fan off immediately.
- Every API route is declared public, protected, or elevation-gated in `tests/test_routes.py`.
- The static bundle handler cannot serve a file outside `ui/dist`.
- Actuator routes reject a valid session whose elevation window has lapsed.
- Repeated bad PINs are locked out progressively.
- A sensor bus that stops responding raises a timeout rather than stalling the poll loop.

## Diagnostics

- Every registry command is an argv vector with no shell metacharacters.
- An unknown command name is rejected rather than executed.
- Probes report `missing` with wiring remediation when a sensor is silent, and
  `not_installed` — not a fault — when no hardware is commissioned for it.
- Relay probes report `disabled` while the actuator master enable is off.

## Dry hardware

- SC1227 boots at 800 x 480 landscape and touch is accurate.
- DHT22, DS18B20 and PCF8591/TEMT6000 pass disconnect, stale and recovery checks.
- Relay load contacts remain open and unpowered.
- Power-on, service restart, browser failure and shutdown keep outputs off.

## Camera

- B0483 enumerates.
- 1920 x 1080 at 15 fps streams reliably.
- Autofocus completes.
- A 9152 x 6944 still is captured.
- Streaming recovers after a still capture.

## Acceptance

Sensors and camera operate while every physical actuator remains unpowered. Water-only and power validation are later phases.

## Network

- WiFi passphrases are written to the child process on stdin, never as argv.
- The API binds loopback unless the operator explicitly publishes it.
- The LAN-exposure toggle reports that a service restart is required.

## GPIO editing

- Reserved lines (I2C, UART, HAT EEPROM) are refused.
- Two functions cannot be assigned the same line.
- A relay line cannot be moved while the actuator master enable is on, or while
  an actuator operation is in flight.
- An invalid change leaves `hardware.toml` byte-for-byte unchanged.
- A valid change preserves every non-pin field in the file.

## AI assistance

- Disabled by default; every request is audited.
- API keys never appear in status output, error messages, or the audit log.
- A rate-limited key fails over to the next key in the pool rather than failing
  the request.
- The assistant has no path to an actuator: it returns text only.
- A growth plan changes no setpoint: automation, actuator enable and the next
  spray time are identical before and after.
- Reading the chamber briefing never calls the model; only an explicit
  generate does.
- A root assessment is stored on the capture row, and a run report on the
  experiment row, so both survive a reload.
- Every grow prompt carries the capability map, so uncommissioned measurements
  are reported as unavailable rather than estimated.
