"""Specimen Card: Pillow grades the hero, Jinja2 lays out the card,
Chromium prints it, Pillow grains the finished card.

Geometry lives here on purpose: identical every time. The brand TOML picks mode and options.
"""
from __future__ import annotations

import base64
import dataclasses
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image

from ..brand import PROJECT_ROOT, BrandError
from .crops import crop_to_ratio
from .render import Renderer
from .treatment import Treatment, open_srgb

TEMPLATES = Path(__file__).resolve().parent / "templates"
WIDTH, HEIGHT, MARGIN = 1080, 1350, 72
MODES = ("falloff", "plate")
FONT_ROLES = {"caps": 700, "text": 300, "mono": 400}  # role -> weight to verify

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class CardError(Exception):
    pass


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def card_config(brand) -> dict:
    f = (brand.raw.get("formats") or {}).get("specimen_card")
    if f is None:
        raise BrandError("[formats.specimen_card] missing from brand config")
    mode = str(f.get("mode", "falloff"))
    if mode not in MODES:
        raise BrandError(f"formats.specimen_card.mode must be one of {', '.join(MODES)}")
    return {
        "mode": mode,
        "photo_role": str(f.get("photo_role", "hero")),
        "name_split": str(f.get("name_split", " - ")),
        "show_drop": bool(f.get("show_drop", True)),
        "grain": bool(f.get("grain", True)),
    }


def load_fonts(brand) -> dict[str, dict]:
    fonts = brand.raw.get("fonts") or {}
    out = {}
    for role in FONT_ROLES:
        spec = fonts.get(role)
        if not spec or "family" not in spec or "file" not in spec:
            raise BrandError(f"fonts.{role} needs 'family' and 'file' in brand config")
        path = (PROJECT_ROOT / spec["file"]).resolve()
        if not path.is_file():
            raise BrandError(f"font file for '{role}' not found: {path}")
        out[role] = {"family": spec["family"], "src": _data_uri(path.read_bytes(), "font/ttf")}
    return out


def layout(mode: str) -> dict:
    if mode == "falloff":
        w = 908
        return {"x": (WIDTH - w) // 2, "y": 94, "photo_w": w, "photo_h": w * 5 // 4, "pad": 0}
    w, pad = 736, 32
    return {"x": (WIDTH - w - 2 * pad) // 2, "y": 142, "photo_w": w, "photo_h": w * 5 // 4, "pad": pad}


def render_card(brand, piece, drop: dict, renderer: Renderer, mode: str,
                html_out: Path | None = None) -> Image.Image:
    cfg = card_config(brand)
    if mode not in MODES:
        raise BrandError(f"unknown card mode '{mode}'")

    photo = piece.photos.get(cfg["photo_role"])
    if photo is None:
        raise CardError(f"no {cfg['photo_role']} photo")

    treatment = Treatment.from_brand(brand)
    box = layout(mode)
    cropped, _ = crop_to_ratio(open_srgb(photo), (4, 5), box["photo_w"])
    graded = treatment.apply(cropped, seed="", grain=False)
    buf = BytesIO()
    graded.save(buf, "PNG")

    fonts = load_fonts(brand)
    title, _, series_label = piece.name.partition(cfg["name_split"])

    html = _env.get_template("specimen_card.html.j2").render(
        width=WIDTH,
        height=HEIGHT,
        margin=MARGIN,
        mode=mode,
        box=box,
        palette=brand.palette,
        fonts=fonts,
        font_checks=[
            {"family": fonts[r]["family"], "query": f'{w} 40px "{fonts[r]["family"]}"'}
            for r, w in FONT_ROLES.items()
        ],
        photo_src=_data_uri(buf.getvalue(), "image/png"),
        code=piece.code,
        drop_code=str(drop.get("code", "")) if cfg["show_drop"] else "",
        title=title.strip(),
        series_label=series_label.strip(),
    )
    if html_out is not None:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(html, encoding="utf-8")

    card = renderer.render(html, WIDTH, HEIGHT)

    if cfg["grain"]:
        grain_only = dataclasses.replace(treatment, saturation=1.0, shadow_lift=0.0)
        card = grain_only.apply(card, seed=f"{brand.id}:{piece.number:03d}:specimen_card:{mode}")
    return card
