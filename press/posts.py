"""Builds a post's assets from its format definition in the brand config."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .brand import PROJECT_ROOT, BrandError
from .compose.crops import crop_to_ratio, parse_ratio
from .compose.render import Renderer
from .compose.specimen_card import card_config, render_card
from .compose.treatment import Treatment, open_srgb, save_png

SOURCES = ("piece", "card", "photo", "file")
PHOTO_TYPES = (".jpg", ".jpeg", ".png", ".webp")


class PostError(Exception):
    pass


def format_config(brand, name: str) -> tuple[str, dict]:
    formats = brand.raw.get("formats") or {}
    key = name.replace("-", "_").lower()
    if key not in formats:
        names = ", ".join(sorted(k.replace("_", "-") for k in formats))
        raise BrandError(f"unknown format '{name}' (available: {names})")
    fmt = formats[key]
    if fmt.get("source") not in SOURCES:
        raise BrandError(f"formats.{key}.source must be one of {', '.join(SOURCES)}")
    return key, fmt


def outbox_root(brand) -> Path:
    raw = str((brand.raw.get("outbox") or {}).get("path", "outbox"))
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path) / brand.id


def outbox_dir(brand, record) -> Path:
    return outbox_root(brand) / f"{record.id:03d}-{record.date or 'unscheduled'}-{record.format}"


def _file_seed(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_assets(brand, catalog, key: str, fmt: dict, pieces: list, photos: list[Path],
                 files: list[Path], ratio_override: str | None, post_dir: Path) -> list[Path]:
    source = fmt["source"]
    slug = key.replace("_", "-")
    width = int((brand.raw.get("crops") or {}).get("width", 1080))
    ratio = parse_ratio(ratio_override or fmt.get("ratio", "4:5"))
    mode = str(fmt.get("treatment", "full"))
    if mode not in ("full", "none"):
        raise BrandError(f"formats.{key}.treatment must be 'full' or 'none'")
    treatment = Treatment.from_brand(brand)

    # Validate everything before touching disk.
    if source in ("piece", "card"):
        if not pieces:
            raise PostError(f"{slug} needs at least one piece number")
        if photos or files:
            raise PostError(f"{slug} renders from the catalog; --photo/--file don't apply")
    if source == "piece":
        role = str(fmt.get("role", "hero"))
        missing = [p.code for p in pieces if role not in p.photos]
        if missing:
            raise PostError(f"no {role} photo for: {', '.join(missing)}")
    if source == "photo" and not photos:
        raise PostError(f"{slug} needs --photo PATH (repeat for a carousel)")
    if source == "file" and not files:
        raise PostError(f"{slug} needs --file PATH")
    for p in [*photos, *files]:
        if not p.is_file():
            raise PostError(f"not a file: {p}")
    for p in photos:
        if p.suffix.lower() not in PHOTO_TYPES:
            raise PostError(f"{p.name}: use {', '.join(PHOTO_TYPES)} (export HEIC as JPEG first)")

    post_dir.mkdir(parents=True)
    out: list[Path] = []

    def finish(img, seed):
        return treatment.apply(img, seed=seed) if mode == "full" else img

    if source == "piece":
        for i, piece in enumerate(pieces, 1):
            img, _ = crop_to_ratio(open_srgb(piece.photos[role]), ratio, width)
            path = post_dir / f"{i:02d}-{slug}-{piece.number:03d}.png"
            save_png(finish(img, f"{brand.id}:{piece.number:03d}:{role}"), path)
            out.append(path)

    elif source == "card":
        card_mode = card_config(brand)["mode"]
        with Renderer() as renderer:
            for i, piece in enumerate(pieces, 1):
                img = render_card(brand, piece, catalog.drop, renderer, card_mode)
                path = post_dir / f"{i:02d}-specimen-{piece.number:03d}.png"
                save_png(img, path)
                out.append(path)

    elif source == "photo":
        for i, src in enumerate(photos, 1):
            img, upscaled = crop_to_ratio(open_srgb(src), ratio, width)
            path = post_dir / f"{i:02d}-{slug}.png"
            save_png(finish(img, f"{brand.id}:photo:{_file_seed(src)}"), path)
            if upscaled:
                print(f"note: {src.name} was smaller than {width}px wide after cropping and got upscaled")
            out.append(path)

    else:
        for i, src in enumerate(files, 1):
            path = post_dir / f"{i:02d}-{src.name}"
            shutil.copy2(src, path)
            out.append(path)

    return out
