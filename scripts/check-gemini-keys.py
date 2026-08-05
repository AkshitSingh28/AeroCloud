#!/usr/bin/env python3
"""Prove every key in a gemini.env actually works before it reaches an appliance.

    ./scripts/check-gemini-keys.py [path/to/gemini.env]

Rotation is the moment a typo is most likely and least visible: the service
restarts, the UI reports "4 keys pooled", and nothing fails until an operator
asks the assistant something during a bring-up session. This makes a real
request on each key and exits non-zero if any of them cannot answer.

Key material is never printed — keys are identified by position and last four
characters, and every upstream error body is redacted before display.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aeroos.ai import API_ROOT, DEFAULT_MODEL, REQUEST_TIMEOUT, load_keys  # noqa: E402


def check(key: str, keys: list[str], model: str) -> tuple[bool, str]:
    request = urllib.request.Request(
        f"{API_ROOT}/{model}:generateContent",
        data=json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": "Reply with: ok"}]}],
                # Room for the model to think before it answers; a reply that is
                # all reasoning and no text would otherwise look like a dead key.
                "generationConfig": {"maxOutputTokens": 800},
            }
        ).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            json.loads(response.read())
        return True, "ok"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        for material in keys:
            body = body.replace(material, "***")
        try:
            message = json.loads(body)["error"]["message"]
        except Exception:
            message = body
        return False, f"HTTP {exc.code} — {message[:90]}"
    except Exception as exc:  # noqa: BLE001 - any failure here is a failed check
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "deploy/gemini.env")
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 1

    keys = load_keys(path)
    if not keys:
        print(f"error: no keys found in {path}", file=sys.stderr)
        return 1

    model = DEFAULT_MODEL
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("AEROOS_GEMINI_MODEL="):
            model = stripped.partition("=")[2].strip().strip("\"'")

    if len(set(keys)) != len(keys):
        print(f"warning: {len(keys) - len(set(keys))} duplicate key(s) — the pool "
              "rotates between identical credentials, which shares one quota")

    print(f"checking {len(keys)} key(s) against {model}\n")
    failures = 0
    for index, key in enumerate(keys, start=1):
        ok, detail = check(key, keys, model)
        label = f"  key {index} (…{key[-4:]})"
        if ok:
            print(f"{label}: ok")
        else:
            print(f"{label}: FAILED — {detail}")
            failures += 1

    print()
    if failures:
        print(f"{failures} of {len(keys)} key(s) failed. Not safe to install.")
        return 1
    print(f"all {len(keys)} key(s) answered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
