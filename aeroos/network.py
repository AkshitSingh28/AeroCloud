"""WiFi provisioning for the appliance.

The AeroOS image runs systemd-networkd with iwd, so this drives `iwctl` rather
than NetworkManager. Passphrases are written to the child process on stdin
instead of being passed as arguments, because argv is world-readable in
/proc while the command runs.

Nothing here is reachable without an elevated operator session, and the joined
passphrase is never stored by AeroOS, echoed back, or written to the audit log —
iwd owns the credential in /var/lib/iwd.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from typing import Any

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
COMMAND_TIMEOUT = 25
SCAN_SETTLE_SECONDS = 3


class NetworkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WifiNetwork:
    ssid: str
    security: str
    signal: int
    connected: bool
    known: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ssid": self.ssid,
            "security": self.security,
            "signal": self.signal,
            "connected": self.connected,
            "known": self.known,
        }


def _clean(text: str) -> str:
    return ANSI.sub("", text).replace("•", "").replace(">", " ").strip()


_SIM_NETWORKS = [
    WifiNetwork("Greenhouse-2G", "psk", 4, True, True),
    WifiNetwork("Greenhouse-5G", "psk", 3, False, True),
    WifiNetwork("Lab-Guest", "psk", 2, False, False),
    WifiNetwork("SetupHotspot", "open", 1, False, False),
]


class NetworkService:
    def __init__(self, *, simulator: bool, interface: str = "wlan0") -> None:
        self.simulator = simulator
        self.interface = interface
        self._sim_connected = "Greenhouse-2G"

    @property
    def available(self) -> bool:
        return self.simulator or shutil.which("iwctl") is not None

    async def _iwctl(self, *args: str, stdin: str | None = None) -> str:
        if shutil.which("iwctl") is None:
            raise NetworkError(
                "iwctl is not installed. AeroOS manages WiFi through iwd; install it or "
                "provision the network from the boot partition instead."
            )
        process = await asyncio.create_subprocess_exec(
            "iwctl",
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(stdin.encode() if stdin is not None else None),
                timeout=COMMAND_TIMEOUT,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise NetworkError("the WiFi subsystem did not respond in time") from None
        output = _clean(stdout.decode("utf-8", errors="replace"))
        if process.returncode:
            raise NetworkError(output.splitlines()[-1] if output else "iwctl failed")
        return output

    # ------------------------------------------------------------------ status

    async def status(self) -> dict[str, Any]:
        if self.simulator:
            return {
                "available": True,
                "interface": self.interface,
                "state": "connected",
                "ssid": self._sim_connected,
                "address": "192.168.1.42",
                "simulated": True,
            }
        if not self.available:
            return {
                "available": False,
                "interface": self.interface,
                "state": "unavailable",
                "ssid": None,
                "address": None,
                "simulated": False,
            }
        try:
            raw = await self._iwctl("station", self.interface, "show")
        except NetworkError as exc:
            return {
                "available": True,
                "interface": self.interface,
                "state": "error",
                "ssid": None,
                "address": None,
                "detail": str(exc),
                "simulated": False,
            }
        state, ssid = "disconnected", None
        for line in raw.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] == "State":
                state = fields[1]
            elif len(fields) >= 3 and fields[0] == "Connected" and fields[1] == "network":
                ssid = " ".join(fields[2:])
        return {
            "available": True,
            "interface": self.interface,
            "state": state,
            "ssid": ssid,
            "address": await self._address(),
            "simulated": False,
        }

    async def _address(self) -> str | None:
        if shutil.which("ip") is None:
            return None
        process = await asyncio.create_subprocess_exec(
            "ip", "-brief", "-4", "addr", "show", self.interface,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        fields = stdout.decode().split()
        return fields[2].split("/")[0] if len(fields) >= 3 else None

    # -------------------------------------------------------------------- scan

    async def scan(self) -> list[dict[str, Any]]:
        if self.simulator:
            await asyncio.sleep(0.4)
            return [network.as_dict() for network in _SIM_NETWORKS]
        await self._iwctl("station", self.interface, "scan")
        await asyncio.sleep(SCAN_SETTLE_SECONDS)
        listing = await self._iwctl("station", self.interface, "get-networks")
        known = await self._known_ssids()
        networks: list[WifiNetwork] = []
        for line in listing.splitlines():
            fields = line.split()
            # Rows are: [>] SSID SECURITY ****  — the trailing stars are signal.
            if len(fields) < 2 or fields[0] in {"Available", "Network", "-"} or set(line.strip()) <= {"-"}:
                continue
            stars = [item for item in fields if set(item) == {"*"}]
            if not stars:
                continue
            signal = len(stars[-1])
            remainder = fields[: fields.index(stars[-1])]
            if len(remainder) < 2:
                continue
            security = remainder[-1]
            ssid = " ".join(remainder[:-1])
            if not ssid:
                continue
            networks.append(
                WifiNetwork(
                    ssid=ssid,
                    security=security,
                    signal=signal,
                    connected=line.strip().startswith(">"),
                    known=ssid in known,
                )
            )
        networks.sort(key=lambda item: (-item.signal, item.ssid))
        return [network.as_dict() for network in networks]

    async def _known_ssids(self) -> set[str]:
        try:
            raw = await self._iwctl("known-networks", "list")
        except NetworkError:
            return set()
        found: set[str] = set()
        for line in raw.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[-1] not in {"Network", "-"}:
                found.add(" ".join(fields[:-1]) if fields[-1] in {"psk", "open"} else fields[0])
        return found

    # ----------------------------------------------------------------- connect

    async def connect(self, ssid: str, passphrase: str | None) -> dict[str, Any]:
        if not ssid.strip():
            raise NetworkError("an SSID is required")
        if self.simulator:
            await asyncio.sleep(0.6)
            self._sim_connected = ssid
            return {"connected": True, "ssid": ssid, "simulated": True}
        # iwctl prompts for the passphrase on stdin when it is not supplied as an
        # argument, which keeps the credential out of the process list.
        await self._iwctl(
            "station", self.interface, "connect", ssid,
            stdin=f"{passphrase}\n" if passphrase else "\n",
        )
        await asyncio.sleep(2)
        state = await self.status()
        if state.get("state") != "connected":
            raise NetworkError(
                f"could not join {ssid}. Check the passphrase and that the network is in range."
            )
        return {"connected": True, "ssid": ssid, "address": state.get("address"), "simulated": False}

    async def disconnect(self) -> dict[str, Any]:
        if self.simulator:
            self._sim_connected = ""
            return {"connected": False, "simulated": True}
        await self._iwctl("station", self.interface, "disconnect")
        return {"connected": False, "simulated": False}

    async def forget(self, ssid: str) -> dict[str, Any]:
        if self.simulator:
            return {"forgotten": True, "ssid": ssid, "simulated": True}
        await self._iwctl("known-networks", ssid, "forget")
        return {"forgotten": True, "ssid": ssid, "simulated": False}
