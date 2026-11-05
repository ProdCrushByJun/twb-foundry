"""Write logo.png: a white disc with three bars in the brand color, on a transparent background (specs/shell.json).

Plain zlib + struct, no imaging library. Run: python data/sample/make_logo.py
"""
import struct
import zlib
from pathlib import Path

SIZE = 96
BRAND = (0x2F, 0x6F, 0x6A)  # specs/shell.json sidebar color
BARS = [(26, 40, 58), (42, 56, 44), (58, 72, 30)]  # (x0, x1, top y) of each bar; all end at y 70


def pixel(x, y):
    c = (SIZE - 1) / 2
    if (x - c) ** 2 + (y - c) ** 2 > (SIZE / 2 - 2) ** 2:
        return (0, 0, 0, 0)
    if any(x0 <= x < x1 and top <= y < 70 for x0, x1, top in BARS):
        return (*BRAND, 255)
    return (255, 255, 255, 255)


def png(path):
    raw = b"".join(b"\x00" + bytes(v for x in range(SIZE) for v in pixel(x, y)) for y in range(SIZE))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
                           + chunk(b"IEND", b""))


if __name__ == "__main__":
    png(Path(__file__).parent / "logo.png")
