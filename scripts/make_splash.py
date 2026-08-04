from __future__ import annotations

import struct
import sys
from pathlib import Path


def write_tga(path: Path, width: int = 1280, height: int = 720) -> None:
    background = (15, 7, 5)
    green = (142, 215, 48)
    pixels = bytearray()
    center_x, center_y = width // 2, height // 2 - 24
    for y in range(height):
        for x in range(width):
            dx = (x - center_x) / 94
            dy = (y - center_y) / 116
            droplet = dx * dx + (dy + 0.12) * (dy + 0.12) < 1 and y > center_y - 115
            taper = abs(dx) < max(0.05, (y - (center_y - 122)) / 165)
            root = abs(x - center_x) < 4 and center_y - 10 < y < center_y + 92
            branches = (
                abs((x - center_x) - (y - center_y - 28) * 0.52) < 4
                or abs((x - center_x) + (y - center_y - 7) * 0.48) < 4
            ) and center_y + 8 < y < center_y + 78
            color = green if droplet and taper else background
            if root or branches:
                color = background
            pixels.extend(color)
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, width, height, 24, 0x20)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + pixels)


if __name__ == "__main__":
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "image/assets/aeroos-splash.tga")
    write_tga(destination)

