from __future__ import annotations

import asyncio
import contextlib
import io
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class StreamingOutput(io.BufferedIOBase):
    """Thread-safe destination for Picamera2's MJPEG encoder."""

    def __init__(self) -> None:
        self.frame: bytes | None = None
        self.sequence = 0
        self.condition = threading.Condition()

    def write(self, buffer: bytes) -> int:
        with self.condition:
            self.frame = bytes(buffer)
            self.sequence += 1
            self.condition.notify_all()
        return len(buffer)

    def wait_for_frame(self, after_sequence: int) -> tuple[int, bytes]:
        with self.condition:
            self.condition.wait_for(
                lambda: self.sequence > after_sequence and self.frame is not None,
                timeout=5,
            )
            if self.frame is None:
                raise TimeoutError("camera frame unavailable")
            return self.sequence, self.frame


class VisionService:
    def __init__(self, image_dir: Path, *, simulator: bool) -> None:
        self.image_dir = image_dir
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.simulator = simulator
        self._random = random.Random(84)
        self._camera_lock = threading.RLock()
        self._camera: Any | None = None
        self._encoder: Any | None = None
        self._file_output: Any | None = None
        self._stream_output = StreamingOutput()

    async def capture_and_analyze(self) -> tuple[str, int, str]:
        if not self.simulator:
            return await asyncio.to_thread(self._capture_physical)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root_area = self._random.randint(17600, 19600)
        path = self.image_dir / f"roots-{stamp}.svg"
        path.write_text(
            """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480" shape-rendering="geometricPrecision">
<rect width="640" height="480" fill="#071019"/>
<g fill="none" stroke="#79aefe" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
<path d="M320 24c-8 84 18 128-4 206-18 62 10 118-22 224"/>
<path d="M318 118c-64 38-84 84-96 146M318 172c66 42 86 92 92 154"/>
<path d="M308 236c-54 34-68 82-58 154M322 286c48 40 42 100 70 154"/>
</g></svg>""",
            encoding="utf-8",
        )
        return str(path), root_area, "good"

    def simulator_live_svg(self) -> str:
        return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480" role="img" aria-label="AeroOS live simulator feed" shape-rendering="geometricPrecision">
<rect width="640" height="480" fill="#071019"/>
<g opacity=".18" stroke="#7390b3" stroke-width="1"><path d="M0 120h640M0 240h640M0 360h640M160 0v480M320 0v480M480 0v480"/></g>
<g opacity=".32" fill="none" stroke="#b8c7d9" stroke-width="2"><path d="M22 58V22h36M582 22h36v36M22 422v36h36M582 458h36v-36"/></g>
<g fill="none" stroke="#79aefe" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
  <path d="M320 24c-8 84 18 128-4 206-18 62 10 118-22 224"/>
  <path d="M318 118c-64 38-84 84-96 146M318 172c66 42 86 92 92 154"/>
  <path d="M308 236c-54 34-68 82-58 154M322 286c48 40 42 100 70 154"/>
  <animate attributeName="opacity" values=".78;1;.78" dur="2.8s" repeatCount="indefinite"/>
</g>
<g fill="#59b5d5" opacity=".78">
  <circle cx="90" cy="450" r="3"><animate attributeName="cy" values="450;70" dur="3.1s" repeatCount="indefinite"/></circle>
  <circle cx="170" cy="470" r="2.5"><animate attributeName="cy" values="470;110" dur="3.8s" repeatCount="indefinite"/></circle>
  <circle cx="430" cy="460" r="3"><animate attributeName="cy" values="460;80" dur="3.4s" repeatCount="indefinite"/></circle>
  <circle cx="540" cy="475" r="2.5"><animate attributeName="cy" values="475;125" dur="4s" repeatCount="indefinite"/></circle>
</g>
<g transform="translate(20 24)"><circle cx="5" cy="5" r="5" fill="#6fa4f2"><animate attributeName="opacity" values=".45;1;.45" dur="1.4s" repeatCount="indefinite"/></circle><text x="18" y="10" fill="#e3edf9" font-family="sans-serif" font-size="13" font-weight="700" letter-spacing="1.4">SIM LIVE · 720P</text></g>
<g transform="translate(500 438)" fill="#aebdce" font-family="monospace" font-size="12"><text>15 FPS</text><text x="54">A1</text></g>
</svg>"""

    def _start_streaming_physical_locked(self) -> None:
        if self._camera is not None:
            return
        try:
            from picamera2 import Picamera2
            from picamera2.encoders import MJPEGEncoder
            from picamera2.outputs import FileOutput
        except ImportError as exc:
            raise RuntimeError(f"AeroOS camera streaming package is incomplete: {exc}") from exc
        camera = Picamera2()
        config = camera.create_video_configuration(
            main={"size": (1920, 1080)},
            controls={"FrameRate": 15},
            buffer_count=4,
        )
        camera.configure(config)
        with contextlib.suppress(Exception):
            camera.set_controls({"AfMode": 2})
        encoder = MJPEGEncoder(bitrate=12_000_000)
        file_output = FileOutput(self._stream_output)
        camera.start_recording(encoder, file_output)
        self._camera = camera
        self._encoder = encoder
        self._file_output = file_output

    def mjpeg_frames(self) -> Iterator[bytes]:
        if self.simulator:
            raise RuntimeError("simulator uses the animated SVG camera feed")
        with self._camera_lock:
            self._start_streaming_physical_locked()
        sequence = 0
        while True:
            try:
                sequence, frame = self._stream_output.wait_for_frame(sequence)
            except TimeoutError:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-store\r\n\r\n"
                + frame
                + b"\r\n"
            )

    def close(self) -> None:
        if self.simulator:
            return
        with self._camera_lock:
            self._stop_streaming_physical_locked()

    def _stop_streaming_physical_locked(self) -> None:
        camera = self._camera
        self._camera = None
        self._encoder = None
        self._file_output = None
        if camera is None:
            return
        try:
            camera.stop_recording()
        finally:
            camera.close()

    def _capture_physical(self) -> tuple[str, int, str]:
        try:
            import cv2
            import numpy as np
            from picamera2 import Picamera2
        except ImportError as exc:
            raise RuntimeError(f"AeroOS camera package is incomplete: {exc}") from exc
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.image_dir / f"roots-{stamp}.jpg"
        with self._camera_lock:
            restore_stream = self._camera is not None
            if restore_stream:
                self._stop_streaming_physical_locked()
            camera = Picamera2()
            config = camera.create_still_configuration(main={"size": (9152, 6944)})
            camera.configure(config)
            camera.start()
            try:
                with contextlib.suppress(Exception):
                    camera.set_controls({"AfMode": 2})
                    camera.autofocus_cycle(wait=True)
                camera.capture_file(str(path))
            finally:
                camera.stop()
                camera.close()
                if restore_stream:
                    self._start_streaming_physical_locked()
        image = cv2.imread(str(path))
        preview = cv2.resize(image, (640, 480))
        gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, threshold = cv2.threshold(blur, 100, 255, cv2.THRESH_BINARY_INV)
        clean = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        root_area = int(np.sum(clean == 255))
        quality = "good" if 500 < root_area < 250000 else "review"
        return str(path), root_area, quality
