from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from aeroos.ai import (
    THINKING_HEADROOM_TOKENS,
    THINKING_LEVEL,
    AIUnavailable,
    GeminiService,
    KeyPool,
    load_keys,
)


def service(keys: list[str], **kwargs) -> GeminiService:
    return GeminiService(keys=keys, enabled=True, simulator=False, **kwargs)


def test_disabled_service_refuses_before_touching_the_network() -> None:
    assistant = GeminiService(keys=["a"], enabled=False)
    with pytest.raises(AIUnavailable, match="disabled"):
        assistant._require_ready()


def test_missing_keys_are_reported_clearly() -> None:
    assistant = GeminiService(keys=[], enabled=True)
    with pytest.raises(AIUnavailable, match="gemini.env"):
        assistant._require_ready()
    assert assistant.ready is False


def test_simulator_is_ready_without_keys_but_physical_mode_is_not() -> None:
    """The stub exists so the workflow can be rehearsed before keys arrive."""
    assert GeminiService(keys=[], enabled=True, simulator=True).ready is True
    assert GeminiService(keys=[], enabled=False, simulator=True).ready is False
    assert GeminiService(keys=[], enabled=True, simulator=False).ready is False


def test_status_never_exposes_key_material() -> None:
    secret = "AIzaSy-super-secret-value"
    payload = repr(service([secret, "second"]).status())
    assert secret not in payload
    assert "key 1" in payload and "key 2" in payload


def test_pool_rotates_across_all_keys() -> None:
    pool = KeyPool.from_values(["one", "two", "three"])
    picked = [pool.acquire().value for _ in range(6)]
    assert picked == ["one", "two", "three", "one", "two", "three"]


def test_pool_skips_a_key_in_cooldown() -> None:
    pool = KeyPool.from_values(["one", "two"])
    first = pool.acquire()
    pool.penalize(first, 60)
    assert pool.acquire().value == "two"
    assert pool.acquire().value == "two"


def test_pool_returns_none_when_every_key_is_resting() -> None:
    pool = KeyPool.from_values(["one", "two"])
    for key in list(pool.keys):
        pool.penalize(key, 60)
    assert pool.acquire() is None


def test_quota_error_fails_over_to_the_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 on the first free-tier key must not fail the operator's request."""
    assistant = service(["exhausted", "healthy"])
    attempts: list[str] = []

    def fake_post(key, payload):
        attempts.append(key.value)
        if key.value == "exhausted":
            raise urllib.error.HTTPError(
                "https://example.invalid", 429, "Too Many Requests", {}, None
            )
        return {"candidates": [{"content": {"parts": [{"text": "diagnosis text"}]}}]}

    monkeypatch.setattr(assistant, "_post", fake_post)
    result = assistant._generate_sync(
        [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=900
    )
    assert result == "diagnosis text"
    assert attempts == ["exhausted", "healthy"]
    assert assistant.pool.keys[0].available is False


def test_every_key_exhausted_raises_with_a_useful_message(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = service(["one", "two"])

    def always_limited(key, payload):
        raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many", {}, None)

    monkeypatch.setattr(assistant, "_post", always_limited)
    with pytest.raises(AIUnavailable, match="rate limited"):
        assistant._generate_sync(
            [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=900
        )


def test_a_retired_model_fails_fast_instead_of_burning_every_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """404 is the model, not the key: rotating cannot fix it and hides the cause."""
    assistant = service(["one", "two", "three", "four"], model="gemini-retired")
    attempts: list[str] = []

    class Gone(urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("https://example.invalid", 404, "Not Found", {}, None)

        def read(self) -> bytes:
            return b'{"error":{"message":"This model is no longer available"}}'

    def fake_post(key, payload):
        attempts.append(key.value)
        raise Gone()

    monkeypatch.setattr(assistant, "_post", fake_post)
    with pytest.raises(AIUnavailable, match="AEROOS_GEMINI_MODEL"):
        assistant._generate_sync(
            [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=900
        )
    assert attempts == ["one"], "should stop after the first key"
    assert all(key.available for key in assistant.pool.keys), "no key should be rested"


def test_thinking_output_is_never_shown_as_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A thinking model's scratchpad is not advice for the operator."""
    assistant = service(["one"])
    monkeypatch.setattr(assistant, "_post", lambda key, payload: {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "Checking: is this advisory only? Yes. Should I mention", "thought": True},
            {"text": "Humidity is trending down about three points a day."},
        ]}}]
    })
    result = assistant._generate_sync(
        [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=900
    )
    assert result == "Humidity is trending down about three points a day."


def test_a_truncated_answer_is_an_error_not_a_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thinking tokens are billed to maxOutputTokens.

    With too small a budget the API returns MAX_TOKENS and a scrap of the
    model's scratchpad. Showing that to an operator standing at a chamber is
    worse than saying the assistant failed.
    """
    assistant = service(["one", "two"])
    monkeypatch.setattr(assistant, "_post", lambda key, payload: {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]
    })
    with pytest.raises(AIUnavailable, match="output budget"):
        assistant._generate_sync(
            [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=10
        )
    assert all(key.available for key in assistant.pool.keys), "a bigger budget, not another key"


def test_thinking_budget_is_added_on_top_of_the_prose_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}
    assistant = service(["one"])

    def capture(key, payload):
        sent.update(payload["generationConfig"])
        return {"candidates": [{"content": {"parts": [{"text": "fine"}]}}]}

    monkeypatch.setattr(assistant, "_post", capture)
    assistant._generate_sync([{"text": "x"}], temperature=0.2, system="b", max_tokens=900)
    assert sent["maxOutputTokens"] == 900 + THINKING_HEADROOM_TOKENS
    assert sent["thinkingConfig"] == {"thinkingLevel": THINKING_LEVEL}


def test_http_error_bodies_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """An upstream error must not echo the key back into the UI or the log."""
    secret = "AIzaSy-leaky-key"
    assistant = service([secret])

    class LeakyError(urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("https://example.invalid", 400, "Bad Request", {}, None)

        def read(self) -> bytes:
            return f'{{"error":"API key {secret} is invalid"}}'.encode()

    monkeypatch.setattr(assistant, "_post", lambda key, payload: (_ for _ in ()).throw(LeakyError()))
    with pytest.raises(AIUnavailable) as excinfo:
        assistant._generate_sync(
            [{"text": "hello"}], temperature=0.2, system="brief", max_tokens=900
        )
    assert secret not in str(excinfo.value)
    assert "***" in str(excinfo.value)
    assert secret not in (assistant.last_error or "")


def test_simulator_answers_without_network_access() -> None:
    assistant = GeminiService(keys=[], enabled=True, simulator=True)
    assistant.pool = KeyPool.from_values(["stub"])
    text = assistant._simulated([{"text": "Subject: dht22 reports no signal"}])
    assert "BCM18" in text
    assert "pull-up" in text


def test_simulator_routes_each_task_to_its_own_stub() -> None:
    """A chamber question must not come back as DHT22 wiring advice.

    Every prompt carries a status blob, so keyword matching on words like
    "missing" routed grow questions into the bring-up answer.
    """
    assistant = GeminiService(keys=[], enabled=True, simulator=True)
    status_noise = '\n\nStatus: {"missing_interlocks": ["reservoir level", "flow"]}'

    grow = assistant._simulated(
        [{"text": "Answer the operator's question...\n\nQuestion: How did the chamber do overnight?" + status_noise}]
    )
    assert "BCM18" not in grow
    assert "overnight" in grow

    briefing = assistant._simulated([{"text": "Write a short shift briefing" + status_noise}])
    assert "shift" not in briefing.lower() or "BCM18" not in briefing
    assert "24 hours" in briefing

    report = assistant._simulated([{"text": "Write a research summary of this run" + status_noise}])
    assert "Root area grew" in report


def test_keys_load_from_an_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEROOS_GEMINI_KEYS", raising=False)
    env = tmp_path / "gemini.env"
    env.write_text(
        '# comment line\nAEROOS_GEMINI_KEYS="one, two ,three,four"\nOTHER=x\n', encoding="utf-8"
    )
    assert load_keys(env) == ["one", "two", "three", "four"]


def test_an_unreadable_key_file_does_not_stop_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_keys runs during start-up; a bad mode must not take the chamber down.

    The image once installed gemini.env as 0600 root:root while the service ran
    as another user, which raised PermissionError inside create_app and left the
    appliance with no control plane at all.
    """
    monkeypatch.delenv("AEROOS_GEMINI_KEYS", raising=False)
    env = tmp_path / "gemini.env"
    env.write_text("AEROOS_GEMINI_KEYS=secret\n", encoding="utf-8")
    env.chmod(0o000)
    try:
        assert load_keys(env) == []
    finally:
        env.chmod(0o600)


def test_environment_overrides_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "gemini.env"
    env.write_text("AEROOS_GEMINI_KEYS=file-key\n", encoding="utf-8")
    monkeypatch.setenv("AEROOS_GEMINI_KEYS", "env-key")
    assert load_keys(env) == ["env-key"]
