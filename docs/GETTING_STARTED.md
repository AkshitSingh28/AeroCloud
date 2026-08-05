# Getting started

Everything here works without hardware. The simulator generates realistic
telemetry and a running experiment, and every feature — including assistance —
is exercised the same way it is on the appliance.

## Run the simulator

```bash
git clone https://github.com/AkshitSingh28/AeroCloud.git aeroos && cd aeroos
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
npm --prefix ui install && npm --prefix ui run build
AEROOS_SIMULATOR=1 .venv/bin/uvicorn aeroos.main:app --port 8080
```

Open <http://127.0.0.1:8080>. The default operator PIN is in
`deploy/aeroos.env.example`; change it before the appliance leaves a bench.

Assistance falls back to a built-in stub when no API key is configured, so the
AI surfaces are usable in simulation without an account.

## Build a Raspberry Pi image

On macOS, or any machine with Docker:

```bash
./scripts/prepare-image.sh
./scripts/build-image-docker.sh
./scripts/verify-image.sh output/image/aeroos-rpi4-*.img.zst
```

On a Pi running 64-bit Raspberry Pi OS with `rpi-image-gen` installed:

```bash
./scripts/prepare-image.sh
cd /path/to/rpi-image-gen && ./rpi-image-gen build -S /path/to/aeroos/image -c aeroos.yaml
```

The result lands in `output/image/` at roughly 1.7 GB compressed. Raspberry Pi
Imager reads `.zst` directly, or:

```bash
zstd -d output/image/aeroos-rpi4-*.img.zst -c | sudo dd of=/dev/diskN bs=4m status=progress
```

The image extends the official Trixie minimal A/B layout with the Pi 4 device
layer, the kiosk session, the hardware profile, the camera gate, GPIO/I²C/1-Wire
configuration, an offline Python wheelhouse, and a branded splash. It boots with
`actuator_master_enable = false`.

`verify-image.sh` inspects a built image before it reaches a card: application
modules present, the offline dependency set installed, the key file readable by
the service user, and the actuator master enable still off. Run it every time —
the wheelhouse must be built on Linux, and `build-image-docker.sh` does that in
a container and proves the set resolves before the build starts.

## Configure assistance

Assistance is off until keys exist. Create them at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) and place up to
four in `deploy/gemini.env`, which is git-ignored:

```
AEROOS_GEMINI_KEYS=key1,key2,key3,key4
```

```bash
./scripts/install-gemini-keys.sh aeroos@aeroos.local
```

Each key is checked against the live API first, and the service is not
restarted unless all of them answer. Keys are copied as a file rather than
passed as an argument, and land at `/etc/aeroos/gemini.env` owned by root and
readable by the service group.

Create the four keys in four different Google Cloud projects. The free tier is
rate-limited per project, so four keys in one project share a single quota and
the rotation buys nothing. AeroOS rests any key reporting a quota error and
fails over to the next. Settings shows each key's state without revealing the
key.

### Rotation

1. Create replacements and install them as above.
2. Delete the previous keys at the provider — new keys do not displace old ones.
3. Rebuild any image built with `--with-keys`; the previous keys are inside it.

An image built with `--with-keys` embeds `deploy/gemini.env` so assistance works
on first boot. That image, and every card written from it, is a credential.
Without the flag the image ships an empty template.

## Development

```bash
.venv/bin/pytest -q
npm --prefix ui run test
npm --prefix ui run build
```

`tests/test_routes.py` pins the trust level of every API route. A new endpoint
that is neither declared public, protected, nor elevation-gated fails the suite
until somebody decides which it is.

<details>
<summary>Known advisory</summary>

<br>

`npm audit` reports one unresolved advisory in `react-router`
(`GHSA-qwww-vcr4-c8h2`, RSC-mode CSRF). There is no fixed release — every
version in the usable range is affected, and downgrading below it reintroduces
fourteen older advisories. AeroOS uses client-side `BrowserRouter` with no RSC
mode, server actions, or data-router mutations, so the vulnerable path is
unreachable. Re-check when an upstream fix ships.

</details>
