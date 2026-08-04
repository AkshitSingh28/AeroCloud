# AeroOS

*Repository: [AeroCloud](https://github.com/AkshitSingh28/AeroCloud)*

AeroOS is a Raspberry Pi 4 Linux appliance for aeroponic control, local monitoring, computer-vision root analysis, and reproducible agricultural research.

The illustrated, prototype-specific hardware build sequence is available in [output/pdf/AeroOS_Hardware_Setup_and_Commissioning_Manual.pdf](output/pdf/AeroOS_Hardware_Setup_and_Commissioning_Manual.pdf).

It is built as two independent product layers:

- A safety-oriented Python control plane that owns sensors, GPIO, scheduling, dosing, persistence, authentication, and the local API.
- A touch-first React shell that boots in fullscreen kiosk mode and provides operations, experiments, analytics, vision, calibration, diagnostics, and settings.

## Bringing up hardware

The **Diagnostics** workspace is the tool for connecting sensors and finding
faults. It has three parts:

- **Sensor bring-up** — every measurement the control plane expects, its live
  value, and whether it is healthy, silent, or simply not wired yet. A sensor
  that reports nothing expands into the specific things to check: the pin it
  should be on, the pull-up it needs, the overlay that has to be in
  `config.txt`, and the failure mode that produces that symptom.
- **Console** — a fixed registry of read-only checks (`i2cdetect`, 1-Wire
  enumeration, `pinctrl get`, `rpicam-hello --list-cameras`, service and kernel
  logs, throttling flags, storage). Each shows its exact argv before it runs.
  There is deliberately no arbitrary shell: this service can energize a pump,
  so a generic command endpoint would be a remote-code-execution surface.
  Appliance-specific checks can be added in `/etc/aeroos/diagnostics.toml` —
  see [deploy/diagnostics.toml.example](deploy/diagnostics.toml.example).
- **Audit trail** — every operator command and every rejection, which is where
  to look when a control was refused and it is not obvious why.

In the simulator the console returns labelled synthetic output so the workflow
can be rehearsed before the Pi is assembled.

## Network

WiFi is provisioned from **Settings → Network & access**: scan, join, forget.
The appliance uses iwd, so passphrases are handed to iwd on the child process's
stdin — never as an argument, which would put them in `/proc` — and AeroOS
neither stores nor logs them.

The control API listens on loopback, so only the touchscreen can reach it. The
same panel has a **Reach the dashboard from other devices** toggle that
publishes it on the LAN. That exposes misting, dosing, and the camera feed to
everyone on the network with only the operator PIN in front of them, so it is
off by default, warns before it takes effect, and applies on the next
`sudo systemctl restart aeroos`.

## Changing GPIO assignments

**Hardware → GPIO assignment** edits the pin map in `/etc/aeroos/hardware.toml`
without an SSH session. Reserved lines are refused: BCM2/3 carry the ADC,
BCM14/15 are the serial console, BCM0/1 are the HAT EEPROM. Two functions cannot
share a line, and a relay line cannot be moved while the actuator master enable
is on — the old GPIO has to be released in a known-safe state first. Moving the
1-Wire pin warns that `dtoverlay=w1-gpio` in `config.txt` has to move with it.

The adapter builds its GPIO objects at start-up, so changes apply on the next
service restart.

## AI assistance

Optional Gemini integration, off until an operator turns it on.

For growing:

- **Chamber briefing** on the home screen — what the last 24 hours looked like,
  what is drifting, and the one thing worth doing next. Generated only when
  asked for; reading it back costs nothing.
- **Growth plan** in Chamber — a target envelope for the crop and stage of the
  active run, held against what the chamber is actually maintaining.
- **Root assessment** in Vision — a capture sent for a visual health read, saved
  onto the capture record so it stays part of the research trail.
- **Run report** in Experiments — environment, delivery, root growth, and
  interruptions across a run, written onto the experiment row.
- **Ask** — a question box in every workspace, answered from this chamber's own
  telemetry.

For bring-up:

- **Explain with AI** on any failing sensor probe or open alert.
- **Diagnose current faults** across the whole appliance.

The prompts carry the capability map, so the assistant knows which measurements
this appliance actually has. It is told to say a value is unavailable rather
than estimate one, and not to give a specific nutrient dose — AeroOS has no
calibrated chemistry instrument.

Two properties are structural, not policy:

- **The assistant is advisory.** There is no code path from a model response to
  a control call. It cannot mist, dose, or change a safety state. A growth plan
  is a suggestion the operator applies by hand; the endpoint returns
  `applied: false` and the controller is never told about it.
- **It is opt-in because data leaves the appliance.** Every request sends
  telemetry and log excerpts to Google, and every call is written to the audit
  trail.

### Adding your keys

Get them from [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
then edit **`deploy/gemini.env`** — the file is git-ignored, so real keys stay
out of this repository:

```
AEROOS_GEMINI_KEYS=key1,key2,key3,key4
```

Install them onto the appliance:

```bash
./scripts/install-gemini-keys.sh aeroos@aeroos.local
```

That copies the file to `/etc/aeroos/gemini.env` as `0640 root:aeroos` and
restarts the service. Drop the argument to install on the Pi itself. The keys
are copied as a file, never passed as an argument, because `argv` is
world-readable in `/proc` while a process runs.

Create the four keys in **four different Google Cloud projects**. The free tier
is rate limited per project, so four keys in one project share one quota and the
rotation buys you nothing. AeroOS rotates between them and rests any key that
returns a quota error instead of failing your request; the Settings panel shows
each key's state without ever revealing the key itself.

Keys are deliberately not baked into the image — the image ships an empty
template, so a flashed card that goes missing is not a leaked credential. In the
simulator the assistant answers from a built-in stub, so the whole workflow can
be rehearsed without keys.

## Operator access

Monitoring is readable without authentication on the local appliance. Commands
that move an actuator — misting, dosing, arming automation, resetting a safety
lockout — additionally require a PIN entered within the last five minutes, not
merely a session that was unlocked earlier in the day. The kiosk browser never
closes, so a session token alone is not evidence that the operator is still
present. Failed PIN attempts back off progressively.

## Run the simulator

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix ui install
npm --prefix ui run build
AEROOS_SIMULATOR=1 .venv/bin/uvicorn aeroos.main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. The simulator operator PIN is `0420`.

The simulator starts a mint experiment and generates complete test telemetry. Physical mode instead reports only commissioned capabilities and leaves missing measurements null.

## Verify

```bash
.venv/bin/pytest -q
npm --prefix ui run test
npm --prefix ui run build
npm --prefix ui audit
```

`tests/test_routes.py` pins the trust level of every API route. A new endpoint
that is neither declared public nor declared protected fails the suite until
somebody decides which it is.

`npm audit` reports one unresolved advisory in `react-router`
(`GHSA-qwww-vcr4-c8h2`, RSC-mode CSRF). There is no fixed release: every version
from 7.12.0 to 8.2.0 is in range, and downgrading below it reintroduces fourteen
older advisories. AeroOS uses client-side `BrowserRouter` routes with no RSC
mode, server actions, or data-router mutations, so the vulnerable path is not
reachable. Re-check when an upstream fix ships.

## Raspberry Pi image

`rpi-image-gen` needs an aarch64 Linux host with loop devices. On a Pi running
64-bit Raspberry Pi OS, install it and build directly:

```bash
./scripts/prepare-image.sh
cd /path/to/rpi-image-gen
./rpi-image-gen build -S /path/to/aeroos/image -c aeroos.yaml
```

On a Mac or any machine with Docker, the same build runs inside a privileged
arm64 container:

```bash
./scripts/prepare-image.sh
./scripts/build-image-docker.sh
```

The result lands in `output/image/`. Flash it with Raspberry Pi Imager or `dd`.

`--with-keys` copies `deploy/gemini.env` into the image so AI assistance works
on first boot. That puts live credentials inside the `.img`: reasonable for a
chamber you own, wrong for an image you intend to share, because anyone who
reads the card reads the keys. Without the flag the image ships an empty key
file and you install keys afterwards with `scripts/install-gemini-keys.sh`.

The image definition extends the official Trixie minimal A/B layout with the Pi 4 device layer, Cage/Chromium kiosk, hardware profile, camera gate, GPIO/I2C/1-Wire configuration, offline Python wheelhouse, and branded splash.

The generated image installs `/etc/aeroos/hardware.toml` with actuator master enable off. Complete the sensor, camera and dry-output gates in [docs/VALIDATION.md](docs/VALIDATION.md) before planning the separate 12 V power phase.

## Safety boundary

The simulator and defaults are development aids, not crop or chemical recommendations. Physical misting and dosing must remain disabled until flow, level, pH, EC, pump delivery, power recovery, and emergency behavior are calibrated and validated on the assembled rig.

## License

MIT — see [LICENSE](LICENSE).
