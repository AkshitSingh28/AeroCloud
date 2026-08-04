"""Gemini assistance for fault diagnosis, root imaging, and telemetry questions.

Three rules shape this module.

1. **Advisory only.** Nothing here can move an actuator. The endpoints return
   text; there is deliberately no code path from a model response to a control
   call. A language model must never be the thing that decides to run a pump.
2. **Opt-in, and it leaves the appliance.** AeroOS is otherwise a local-only
   system. Every request ships chamber data to Google, so the feature is off
   until an operator enables it, and every call is written to the audit log.
3. **No new dependencies.** The image installs from an offline wheelhouse, so
   this uses urllib from the standard library rather than an HTTP client.

Free-tier keys are rate limited per project, so the pool rotates across keys and
puts one aside when it reports a quota error instead of failing the request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gemini-3.6-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 90
QUOTA_COOLDOWN_SECONDS = 60.0
ERROR_COOLDOWN_SECONDS = 15.0

# Current Gemini models think before answering, and those tokens are billed
# against maxOutputTokens. A diagnostic prompt carrying probe output and logs
# provokes 800+ thinking tokens, so a budget sized for the prose alone returns a
# truncated fragment of the model's own scratchpad instead of an answer. Reserve
# the thinking separately and keep the level low: this is an appliance on a
# free-tier quota, not a reasoning benchmark.
THINKING_HEADROOM_TOKENS = 1200
THINKING_LEVEL = "low"

SYSTEM_BRIEF = """You are the on-device assistant for AeroOS, a Raspberry Pi 4 aeroponic
research appliance. You help an operator bring up hardware and interpret faults.

Hardware profile: DHT22 chamber climate, DS18B20 solution temperature on 1-Wire,
TEMT6000 light through a PCF8591 ADC on I2C, an Arducam B0483 on CSI, and mist
and fan relays that stay electrically disabled until commissioning.

Rules you must follow:
- You are advisory only. You cannot run commands or actuate anything. Never
  claim to have done so, and never instruct the operator to bypass a safety
  interlock or enable the actuator master while interlocks are missing.
- Be concrete and physical. Name pins, pull-ups, overlays, and voltages.
- If the evidence does not identify the fault, say what to measure next.
- Keep answers under 200 words unless asked to expand. No preamble."""

GROWER_BRIEF = """You are the on-device grow assistant for AeroOS, a Raspberry Pi 4 aeroponic
research chamber. You read the chamber's own telemetry and help the operator run
a better experiment.

What the chamber can actually measure: air temperature and humidity (DHT22),
solution temperature (DS18B20), coarse ambient light (TEMT6000 through an 8-bit
ADC), root imagery (Arducam B0483), and mist delivery events. pH, EC, reservoir
level and flow are usually NOT commissioned — the capability list in the data
tells you which are real.

Rules you must follow:
- You are advisory only. You cannot mist, dose, change a setpoint, or alter a
  safety state, and you must never claim to have done so. Recommendations are
  for the operator to apply deliberately.
- Never invent a measurement. If a field is null the chamber cannot see it; say
  so rather than estimating it from the others.
- Never tell the operator to enable the actuator master, raise a duration cap,
  or bypass an interlock. Those are commissioning decisions with a physical
  validation gate behind them.
- Nutrient and chemical advice stays general and cites that AeroOS has no
  calibrated chemistry instrument. Do not give a specific dose to add.
- Be specific about this chamber and this run. Cite the numbers you were given.
- Plain prose in short paragraphs. No preamble, no markdown headings."""


class AIUnavailable(RuntimeError):
    pass


def _redact(text: str, keys: list[str]) -> str:
    """Strip API keys out of anything that could reach a log or the UI."""
    for key in keys:
        if key:
            text = text.replace(key, "***")
    return text


@dataclass
class PooledKey:
    value: str
    label: str
    cooldown_until: float = 0.0
    calls: int = 0
    failures: int = 0

    @property
    def available(self) -> bool:
        return time.time() >= self.cooldown_until


@dataclass
class KeyPool:
    """Round-robin over the configured keys, skipping any in cooldown."""

    keys: list[PooledKey] = field(default_factory=list)
    _cursor: int = 0

    @classmethod
    def from_values(cls, values: list[str]) -> KeyPool:
        return cls(
            keys=[
                PooledKey(value=value.strip(), label=f"key {index + 1}")
                for index, value in enumerate(values)
                if value.strip()
            ]
        )

    def __len__(self) -> int:
        return len(self.keys)

    def acquire(self) -> PooledKey | None:
        for _ in range(len(self.keys)):
            candidate = self.keys[self._cursor % len(self.keys)]
            self._cursor = (self._cursor + 1) % len(self.keys)
            if candidate.available:
                return candidate
        return None

    def penalize(self, key: PooledKey, seconds: float) -> None:
        key.cooldown_until = time.time() + seconds
        key.failures += 1

    def status(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "label": key.label,
                "available": key.available,
                "cooldown_seconds": max(0, round(key.cooldown_until - now)),
                "calls": key.calls,
                "failures": key.failures,
            }
            for key in self.keys
        ]


def load_keys(env_path: Path | None) -> list[str]:
    """Read keys from the environment, falling back to a root-only env file.

    AEROOS_GEMINI_KEYS accepts a comma-separated list. The file uses the same
    shape as the other AeroOS environment files so it can be dropped in by the
    image build or edited over a console session.
    """
    raw = os.getenv("AEROOS_GEMINI_KEYS", "")
    if not raw and env_path and env_path.exists():
        try:
            content = env_path.read_text(encoding="utf-8")
        except OSError:
            # This runs during application start-up. A key file the service
            # cannot read is a reason to have no assistant, never a reason for
            # the control plane not to boot — the chamber has plants in it.
            return []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "AEROOS_GEMINI_KEYS":
                raw = value.strip().strip('"').strip("'")
                break
    return [item for item in (part.strip() for part in raw.split(",")) if item]


class GeminiService:
    def __init__(
        self,
        *,
        keys: list[str],
        model: str = DEFAULT_MODEL,
        enabled: bool = False,
        simulator: bool = False,
    ) -> None:
        self.pool = KeyPool.from_values(keys)
        self.model = model
        self.enabled = enabled
        self.simulator = simulator
        self.last_error: str | None = None

    # ------------------------------------------------------------------ state

    @property
    def configured(self) -> bool:
        return len(self.pool) > 0

    @property
    def ready(self) -> bool:
        """Whether a request would be served.

        The simulator answers from the built-in stub, so the whole workflow can
        be rehearsed on a laptop before any key exists. Physical mode needs a
        real key: there is nothing to fall back to.
        """
        return self.enabled and (self.configured or self.simulator)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "ready": self.ready,
            "simulated": self.simulator,
            "model": self.model,
            "key_count": len(self.pool),
            "keys": self.pool.status(),
            "last_error": self.last_error,
            "notice": (
                "Requests send chamber telemetry, log excerpts, and any selected "
                "root image to Google. Responses are advisory and cannot actuate."
            ),
        }

    def _require_ready(self) -> None:
        if not self.enabled:
            raise AIUnavailable(
                "AI assistance is disabled. Enable it in Settings to send data off the appliance."
            )
        if not self.configured and not self.simulator:
            raise AIUnavailable(
                "No Gemini keys configured. Add AEROOS_GEMINI_KEYS to /etc/aeroos/gemini.env."
            )

    # --------------------------------------------------------------- requests

    def _post(self, key: PooledKey, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_ROOT}/{self.model}:generateContent"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key.value,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def _generate_sync(
        self, parts: list[dict[str, Any]], *, temperature: float, system: str, max_tokens: int
    ) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens + THINKING_HEADROOM_TOKENS,
                "thinkingConfig": {"thinkingLevel": THINKING_LEVEL},
            },
        }
        attempts = max(1, len(self.pool))
        raw_keys = [key.value for key in self.pool.keys]
        last_failure = "no Gemini key was available"
        for _ in range(attempts):
            key = self.pool.acquire()
            if key is None:
                break
            key.calls += 1
            try:
                body = self._post(key, payload)
            except urllib.error.HTTPError as exc:
                detail = _redact(exc.read().decode("utf-8", errors="replace")[:400], raw_keys)
                if exc.code == 404:
                    # The model is gone, not the key. Google retires models and
                    # gates older ones to existing accounts, so every key in the
                    # pool fails identically — resting all four helps nobody and
                    # buries the real cause under a quota message.
                    self.last_error = (
                        f"Model '{self.model}' is unavailable: {detail} Set AEROOS_GEMINI_MODEL "
                        "in /etc/aeroos/gemini.env to a current model and restart aeroos."
                    )
                    raise AIUnavailable(self.last_error) from exc
                if exc.code in (429, 503):
                    # Free-tier quota. Rest this key and try the next one.
                    self.pool.penalize(key, QUOTA_COOLDOWN_SECONDS)
                    last_failure = f"{key.label} is rate limited"
                    continue
                if exc.code == 400 and "thinking" in detail.lower():
                    # An older model that predates thinkingConfig. Drop it and
                    # retry rather than reporting the key as rejected — the
                    # operator is free to pin any model in gemini.env.
                    payload["generationConfig"].pop("thinkingConfig", None)
                    last_failure = f"{self.model} does not accept thinkingConfig"
                    continue
                if exc.code in (400, 401, 403):
                    self.pool.penalize(key, QUOTA_COOLDOWN_SECONDS)
                    last_failure = f"{key.label} was rejected ({exc.code}): {detail}"
                    continue
                self.pool.penalize(key, ERROR_COOLDOWN_SECONDS)
                last_failure = f"Gemini returned {exc.code}: {detail}"
                continue
            except (urllib.error.URLError, TimeoutError) as exc:
                self.pool.penalize(key, ERROR_COOLDOWN_SECONDS)
                last_failure = (
                    f"could not reach Gemini ({_redact(str(exc.reason if hasattr(exc, 'reason') else exc), raw_keys)}). "
                    "Check the appliance network connection."
                )
                continue
            text = self._extract(body)
            if text:
                self.last_error = None
                return text
            if self._truncated(body):
                # Answering would need a bigger budget, and every other key in
                # the pool would truncate at exactly the same point.
                self.last_error = (
                    "Gemini ran out of output budget before it finished answering. "
                    "This prompt needs a larger maxOutputTokens or a lighter thinking level."
                )
                raise AIUnavailable(self.last_error)
            last_failure = "Gemini returned an empty response"
            self.pool.penalize(key, ERROR_COOLDOWN_SECONDS)
        self.last_error = last_failure
        raise AIUnavailable(last_failure)

    @staticmethod
    def _extract(body: dict[str, Any]) -> str:
        """Answer text only.

        Thinking models can return their scratchpad as parts flagged `thought`.
        Those are the model reasoning about the operator's chamber, not advice
        for the operator, and rendering them as an answer is worse than showing
        nothing — it reads as a broken, half-formed instruction.
        """
        for candidate in body.get("candidates", []):
            chunks = [
                part["text"]
                for part in candidate.get("content", {}).get("parts", [])
                if isinstance(part.get("text"), str) and not part.get("thought")
            ]
            if chunks:
                return "\n".join(chunks).strip()
        return ""

    @staticmethod
    def _truncated(body: dict[str, Any]) -> bool:
        return any(
            candidate.get("finishReason") == "MAX_TOKENS"
            for candidate in body.get("candidates", [])
        )

    async def generate(
        self,
        parts: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        system: str = SYSTEM_BRIEF,
        max_tokens: int = 900,
    ) -> str:
        self._require_ready()
        if self.simulator:
            return self._simulated(parts)
        return await asyncio.to_thread(
            self._generate_sync,
            parts,
            temperature=temperature,
            system=system,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _simulated(parts: list[dict[str, Any]]) -> str:
        """Route to a stub by the prompt's opening instruction.

        Matching on loose keywords does not work here: every prompt carries a
        status blob, and words like "missing" or "image" appear in telemetry
        that has nothing to do with the task. Each task helper above opens with
        a distinctive phrase, so that is what selects the answer.
        """
        text = " ".join(part.get("text", "") for part in parts).lower()
        question = text.partition("question:")[2].partition("\n")[0]
        if any("inline_data" in part for part in parts) or "root-zone photograph" in text:
            return (
                "[simulator] Root mass looks evenly distributed with white, turgid tips and no "
                "browning at the crown. Density is consistent with healthy oxygenation.\n\n"
                "Watch for: any tan discolouration near the base, which is the first sign of "
                "root rot in a warm reservoir.\n\n"
                "Configure Gemini keys to get a real assessment."
            )
        if "shift briefing" in text:
            return (
                "[simulator] The chamber held 24.8 °C average air temperature over the last 24 "
                "hours, peaking at 27.1 °C in the afternoon, with humidity between 61 and 74%. "
                "Solution temperature tracked air closely at 23.9 °C. Nothing left the safe "
                "envelope and no alert was raised.\n\n"
                "Humidity is drifting down about three points a day. In a closed chamber that "
                "usually means the mist cycle is landing less water than it did — worth "
                "confirming the nozzles are not partly blocked before adjusting cadence.\n\n"
                "Next: take a root capture. The last one is 19 hours old, and root imagery is the "
                "only growth signal this chamber records.\n\n"
                "Configure Gemini keys for a briefing on your real telemetry."
            )
        if "target envelope" in text:
            return (
                "[simulator] For mint in vegetative growth, aim for 20–25 °C air, 60–70% relative "
                "humidity, and solution temperature at or just below air — above roughly 24 °C "
                "the solution holds less dissolved oxygen and root health degrades. Photoperiod "
                "of 16 hours suits vegetative growth. A 2 s mist every 5 minutes is a reasonable "
                "aeroponic starting cadence.\n\n"
                "Against those targets, this chamber runs about 1 °C warm in the afternoon and "
                "otherwise sits inside the envelope. The largest gap is that it cannot verify "
                "delivery: with no flow sensor commissioned, a blocked nozzle looks identical to "
                "a healthy cycle in the telemetry.\n\n"
                "These are suggestions. AeroOS will not adopt them; apply what you agree with.\n\n"
                "Configure Gemini keys for advice on your actual crop and conditions."
            )
        if "research summary" in text:
            return (
                "[simulator] Over the run the chamber held 24.6 °C mean air temperature (21.2–"
                "28.4 °C) and 66% mean humidity, with solution temperature 0.7 °C below air "
                "throughout. Delivery totalled 412 mist cycles for roughly 14 minutes of pump "
                "time; no cycle failed and no dosing was performed.\n\n"
                "Root area grew from 12,050 px² to 18,420 px², about 53% over the run, with the "
                "steepest gain in the middle third. pH and EC were never commissioned, so this "
                "run has no chemistry data and no nutrient conclusion can be drawn from it.\n\n"
                "For the next run, commission flow verification first — without it the delivery "
                "figures above are commanded time, not confirmed water.\n\n"
                "Configure Gemini keys to generate a report from your real run."
            )
        # Bring-up: only when the subject or the question is actually the DHT22.
        # The word "missing" alone is not enough — it appears in every status
        # blob that carries a missing interlock.
        subject = text.partition("subject:")[2].partition("\n")[0]
        if "dht22" in subject or "dht22" in question or "diagnose this aeroos appliance" in text:
            return (
                "[simulator] The DHT22 is not returning a reading.\n\n"
                "1. Confirm DATA is on BCM18 (physical pin 12) and not physical pin 18.\n"
                "2. Add a 4.7k–10k pull-up between DATA and 3.3 V; the sensor will not respond "
                "reliably without one.\n"
                "3. Power from 3.3 V, never 5 V — the GPIO input is not 5 V tolerant.\n"
                "4. If a scope shows the start pulse but no data, the sensor is likely dead.\n\n"
                "Configure Gemini keys for a live analysis of your actual logs."
            )
        if subject:
            return (
                f"[simulator] “{subject.strip()[:80]}” is the fault AeroOS raised.\n\n"
                "A real assessment would name the likely physical cause, the order to check "
                "things in, and what each symptom rules out. The stub cannot do that — it has no "
                "model behind it.\n\n"
                "Configure Gemini keys in /etc/aeroos/gemini.env for a real explanation of this "
                "fault."
            )
        if question:
            return (
                f"[simulator] Answering “{question.strip()[:120]}” from this chamber's own "
                "telemetry.\n\n"
                "Over the last 24 hours air temperature averaged 24.8 °C and humidity 66%, both "
                "inside the safe envelope, and no alert is open. pH, EC, reservoir level and flow "
                "are not commissioned on this appliance, so any question about them has no data "
                "behind it and the assistant will say so rather than estimate.\n\n"
                "Configure Gemini keys for a real answer about your chamber."
            )
        return (
            "[simulator] AI assistance is running against the built-in stub. Add Gemini keys to "
            "/etc/aeroos/gemini.env and enable AI in Settings for real answers."
        )

    # ------------------------------------------------------------ task helpers

    async def diagnose(self, context: dict[str, Any]) -> str:
        prompt = (
            "Diagnose this AeroOS appliance. Identify the most likely physical cause of each "
            "fault and give the operator an ordered checklist of what to verify.\n\n"
            f"System state: {context.get('state')} — {context.get('reason')}\n"
            f"Simulator: {context.get('simulator')}\n\n"
            f"Sensor probes:\n{json.dumps(context.get('probes', []), indent=2)[:6000]}\n\n"
            f"Open alerts:\n{json.dumps(context.get('alerts', []), indent=2)[:2000]}\n\n"
            f"Recent console output:\n{str(context.get('console', ''))[:6000]}"
        )
        return await self.generate([{"text": prompt}])

    async def explain_error(self, subject: str, detail: str, extra: str = "") -> str:
        prompt = (
            f"Explain this AeroOS fault to the operator and give the fix.\n\n"
            f"Subject: {subject}\n"
            f"Detail: {detail}\n"
            f"{('Supporting output:' + chr(10) + extra[:5000]) if extra else ''}"
        )
        return await self.generate([{"text": prompt}])

    async def analyze_capture(self, image: bytes, mime_type: str, notes: str = "") -> str:
        prompt = (
            "This is a root-zone photograph from an aeroponic chamber. Assess root health: "
            "colour, density, tip condition, and any sign of rot, drying, or biofilm. State what "
            "the operator should watch or change. Do not invent measurements you cannot see.\n\n"
            f"{notes}"
        )
        return await self.generate(
            [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                },
            ],
            temperature=0.15,
        )

    # ------------------------------------------------------------------- grow

    async def briefing(self, context: dict[str, Any]) -> str:
        """The chamber's own read on the last 24 hours, for the home screen."""
        prompt = (
            "Write a short shift briefing for the operator of this chamber. Three short "
            "paragraphs, no headings: what the last 24 hours looked like, anything drifting or "
            "worth attention, and the single most useful thing to do next. If everything is "
            "steady, say that plainly instead of inventing a concern.\n\n"
            f"Chamber: {context.get('chamber')}\n"
            f"State: {context.get('state')} — {context.get('reason')}\n"
            f"Run: {json.dumps(context.get('experiment'), indent=2)}\n"
            f"Measurable capabilities: {json.dumps(context.get('capabilities', {}))}\n\n"
            f"Latest reading:\n{json.dumps(context.get('sensors', {}), indent=2)[:1500]}\n\n"
            f"Last 24 h:\n{json.dumps(context.get('window'), indent=2)[:2000]}\n\n"
            f"The 24 h before that (for direction, not for reporting):\n"
            f"{json.dumps(context.get('previous'), indent=2)[:2000]}\n\n"
            f"Mist and dosing activity:\n{json.dumps(context.get('delivery'), indent=2)[:1200]}\n\n"
            f"Root captures:\n{json.dumps(context.get('captures', []), indent=2)[:1500]}\n\n"
            f"Open alerts:\n{json.dumps(context.get('alerts', []), indent=2)[:1500]}"
        )
        return await self.generate([{"text": prompt}], temperature=0.3, system=GROWER_BRIEF)

    async def growth_plan(self, context: dict[str, Any]) -> str:
        """Target envelope for the crop, compared against what the chamber holds."""
        prompt = (
            "Recommend an environmental target envelope for this crop at this stage, then "
            "compare it against what this chamber is actually holding and name the largest gap. "
            "Give target ranges for air temperature, relative humidity, solution temperature, "
            "photoperiod, and mist cadence. Mark any target the chamber cannot currently measure "
            "as unverifiable here. These are suggestions for the operator to apply by hand — the "
            "chamber will not adopt them.\n\n"
            f"Crop: {context.get('crop')}\n"
            f"Growth stage: {context.get('stage')}\n"
            f"Operator goal: {context.get('goal') or 'healthy, reproducible growth'}\n"
            f"Days into the run: {context.get('day')}\n"
            f"Measurable capabilities: {json.dumps(context.get('capabilities', {}))}\n\n"
            f"Current conditions:\n{json.dumps(context.get('sensors', {}), indent=2)[:1500]}\n\n"
            f"Last 24 h:\n{json.dumps(context.get('window'), indent=2)[:2000]}\n\n"
            f"Current mist profile:\n{json.dumps(context.get('profile'), indent=2)[:800]}"
        )
        return await self.generate([{"text": prompt}], temperature=0.35, system=GROWER_BRIEF)

    async def experiment_report(self, context: dict[str, Any]) -> str:
        """Narrative summary of a research run, written to the experiment record."""
        prompt = (
            "Write a research summary of this experiment run for the operator's notebook. "
            "Cover: the environment the chamber actually held over the run, how much water was "
            "delivered, how the root imagery developed, anything that interrupted the run, and "
            "what to change in the next run. Cite the numbers. Where a measurement was never "
            "commissioned, state that the run has no data for it rather than glossing over it. "
            "Do not claim a result the telemetry does not support.\n\n"
            f"Experiment: {json.dumps(context.get('experiment'), indent=2)}\n"
            f"Measurable capabilities: {json.dumps(context.get('capabilities', {}))}\n\n"
            f"Environment across the run:\n{json.dumps(context.get('window'), indent=2)[:2500]}\n\n"
            f"Delivery:\n{json.dumps(context.get('delivery'), indent=2)[:1200]}\n\n"
            f"Root captures in order:\n{json.dumps(context.get('captures', []), indent=2)[:3000]}\n\n"
            f"Alerts raised during the run:\n{json.dumps(context.get('alerts', []), indent=2)[:2000]}"
        )
        return await self.generate(
            [{"text": prompt}], temperature=0.25, system=GROWER_BRIEF, max_tokens=1400
        )

    async def ask(self, question: str, context: dict[str, Any], scope: str = "chamber") -> str:
        # The question box appears in Diagnostics and in every grow workspace.
        # A hardware bring-up question and a "how is my mint doing" question want
        # different framing, so the caller says which surface it came from.
        system = SYSTEM_BRIEF if scope == "hardware" else GROWER_BRIEF
        prompt = (
            "Answer the operator's question using only the appliance data below. If the data "
            "does not contain the answer, say so.\n\n"
            f"Question: {question}\n\n"
            f"Chamber: {context.get('chamber')}\n"
            f"Run: {json.dumps(context.get('experiment'), indent=2)[:600]}\n\n"
            f"Status: {json.dumps(context.get('status', {}), indent=2)[:3000]}\n\n"
            f"Latest reading: {json.dumps(context.get('sensors', {}), indent=2)[:1500]}\n\n"
            f"24 h statistics: {json.dumps(context.get('statistics', {}), indent=2)[:1500]}\n\n"
            f"Recent alerts: {json.dumps(context.get('alerts', []), indent=2)[:1500]}"
        )
        return await self.generate([{"text": prompt}], temperature=0.3, system=system)
