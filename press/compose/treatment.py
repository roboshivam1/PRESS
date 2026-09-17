"""Post treatment, applied identically to every asset.

Pipeline: open as sRGB -> crop (crops.py) -> desaturate -> warm shadow lift -> grain.
Grain is seeded from the asset identity, so re-renders are byte-identical.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

from ..brand import HEX, BrandError

SRGB = ImageCms.createProfile("sRGB")
SRGB_ICC = ImageCms.ImageCmsProfile(SRGB).tobytes()
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def open_srgb(path: Path) -> Image.Image:
    img = Image.open(path)
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    if icc:
        try:
            if img.mode not in ("RGB", "CMYK"):
                img = img.convert("RGB")
            src = ImageCms.ImageCmsProfile(BytesIO(icc))
            img = ImageCms.profileToProfile(img, src, SRGB, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass  # unreadable or mismatched profile: fall back to plain conversion
    return img.convert("RGB")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", icc_profile=SRGB_ICC)


@dataclass(frozen=True)
class Treatment:
    saturation: float
    shadow_lift: float
    shadow_tint: tuple[float, float, float]
    grain_strength: float
    grain_size: float

    @classmethod
    def from_brand(cls, brand) -> "Treatment":
        t = brand.raw.get("treatment") or {}
        tint = str(t.get("shadow_tint", "bulb"))
        hexv = brand.palette.get(tint, tint)
        if not HEX.match(hexv):
            raise BrandError(f"treatment.shadow_tint '{tint}' is not a palette token or hex colour")
        rgb = [int(hexv[i:i + 2], 16) for i in (1, 3, 5)]
        peak = max(rgb) or 1
        return cls(
            saturation=float(t.get("saturation", 0.85)),
            shadow_lift=float(t.get("shadow_lift", 14)),
            shadow_tint=tuple(c / peak for c in rgb),
            grain_strength=float(t.get("grain_strength", 6)),
            grain_size=max(1.0, float(t.get("grain_size", 1.4))),
        )

    def apply(self, img: Image.Image, seed: str) -> Image.Image:
        a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        lum = a @ LUMA

        # Desaturate around luminance, so brightness is preserved.
        a = lum[..., None] + (a - lum[..., None]) * self.saturation

        # Warm shadow lift: full strength at black, zero by mid-grey.
        weight = np.clip(1.0 - lum / 0.5, 0.0, 1.0) ** 2
        tint = np.array(self.shadow_tint, dtype=np.float32)
        a = a + (self.shadow_lift / 255.0) * weight[..., None] * tint

        # Mono film grain, strongest in the midtones.
        if self.grain_strength > 0:
            h, w = lum.shape
            rng = np.random.default_rng(
                int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big")
            )
            gh, gw = max(1, round(h / self.grain_size)), max(1, round(w / self.grain_size))
            noise = rng.normal(0.0, 1.0, (gh, gw)).astype(np.float32)
            if (gh, gw) != (h, w):
                noise = np.asarray(Image.fromarray(noise).resize((w, h), Image.BICUBIC))
            midtone = 0.35 + 0.65 * (4.0 * lum * (1.0 - lum))
            a = a + (noise * midtone * (self.grain_strength / 255.0))[..., None]

        return Image.fromarray((np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
