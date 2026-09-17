"""Role crops: cut to an exact ratio, then resize to the output width."""
from __future__ import annotations

import re

from PIL import Image

RATIO = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


def parse_ratio(value: str) -> tuple[int, int]:
    m = RATIO.match(str(value))
    if not m or int(m[1]) == 0 or int(m[2]) == 0:
        raise ValueError(f"invalid ratio '{value}', expected like '4:5'")
    return int(m[1]), int(m[2])


def crop_to_ratio(
    img: Image.Image,
    ratio: tuple[int, int],
    width: int,
    anchor: tuple[float, float] = (0.5, 0.5),
) -> tuple[Image.Image, bool]:
    """Returns (image, upscaled). upscaled=True means the source was smaller than the output."""
    rw, rh = ratio
    src_w, src_h = img.size
    target = rw / rh

    if src_w / src_h > target:
        crop_w, crop_h = round(src_h * target), src_h
    else:
        crop_w, crop_h = src_w, round(src_w / target)

    x = round((src_w - crop_w) * anchor[0])
    y = round((src_h - crop_h) * anchor[1])
    box = img.crop((x, y, x + crop_w, y + crop_h))

    out_h = round(width * rh / rw)
    return box.resize((width, out_h), Image.LANCZOS), crop_w < width
