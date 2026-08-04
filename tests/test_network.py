from __future__ import annotations

import pytest

from aeroos.network import NetworkError, NetworkService, _clean


def test_ansi_and_iwctl_decorations_are_stripped() -> None:
    raw = "\x1b[1;32m  > Greenhouse-2G  psk  ****\x1b[0m"
    assert _clean(raw) == "Greenhouse-2G  psk  ****"


@pytest.mark.asyncio
async def test_simulator_scan_returns_sorted_networks() -> None:
    networks = await NetworkService(simulator=True).scan()
    signals = [item["signal"] for item in networks]
    assert signals == sorted(signals, reverse=True)
    assert {"ssid", "security", "signal", "connected", "known"} <= set(networks[0])


@pytest.mark.asyncio
async def test_simulator_connect_updates_status() -> None:
    service = NetworkService(simulator=True)
    await service.connect("Lab-Guest", "hunter2hunter2")
    assert (await service.status())["ssid"] == "Lab-Guest"


@pytest.mark.asyncio
async def test_empty_ssid_is_rejected() -> None:
    with pytest.raises(NetworkError, match="SSID is required"):
        await NetworkService(simulator=True).connect("   ", "passphrase")


@pytest.mark.asyncio
async def test_passphrase_is_sent_on_stdin_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """argv is world-readable in /proc, so the WiFi secret must not go there."""
    service = NetworkService(simulator=False)
    seen: dict[str, object] = {}

    async def fake_iwctl(*args: str, stdin: str | None = None) -> str:
        seen["args"] = args
        seen["stdin"] = stdin
        return "State  connected\nConnected network  Greenhouse-2G"

    async def fake_status() -> dict[str, object]:
        return {"state": "connected", "address": "192.168.1.42"}

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service, "_iwctl", fake_iwctl)
    monkeypatch.setattr(service, "status", fake_status)
    monkeypatch.setattr("aeroos.network.asyncio.sleep", no_sleep)
    await service.connect("Greenhouse-2G", "correct horse battery")

    assert "correct horse battery" not in " ".join(seen["args"])  # type: ignore[arg-type]
    assert seen["stdin"] == "correct horse battery\n"


@pytest.mark.asyncio
async def test_status_reports_unavailable_without_iwctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeroos.network.shutil.which", lambda _: None)
    state = await NetworkService(simulator=False).status()
    assert state["available"] is False
    assert state["state"] == "unavailable"


def test_scan_parses_iwctl_table() -> None:
    service = NetworkService(simulator=False)
    listing = """                               Available networks
--------------------------------------------------------------------------------
      Network name                  Security            Signal
--------------------------------------------------------------------------------
  >   Greenhouse 2G                 psk                 ****
      Lab-Guest                     psk                 ***
      OpenAP                        open                *
"""
    rows = []
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] in {"Available", "Network", "-"} or set(line.strip()) <= {"-"}:
            continue
        stars = [item for item in fields if set(item) == {"*"}]
        if not stars:
            continue
        remainder = fields[: fields.index(stars[-1])]
        rows.append((" ".join(remainder[:-1]), remainder[-1], len(stars[-1])))
    assert rows == [("> Greenhouse 2G", "psk", 4), ("Lab-Guest", "psk", 3), ("OpenAP", "open", 1)]
    assert service.interface == "wlan0"
