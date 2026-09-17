"""PRESS command line. Sets and prints. Never publishes."""
from __future__ import annotations

import argparse
import re
import sys

from PIL import Image

from .brand import PROJECT_ROOT, BrandError, load_brand
from .compose.crops import crop_to_ratio, parse_ratio
from .compose.treatment import Treatment, open_srgb, save_png
from .sources import PHOTO_ROLES, get_source
from .cli_card import register_card
from .cli_post import register_posts

MISSING = re.compile(r"^No\. (\d{3}): missing (\w+) photo$")


def summarise_warnings(warnings: list[str]) -> list[str]:
    grouped: dict[str, list[int]] = {}
    rest = []
    for w in warnings:
        m = MISSING.match(w)
        if m:
            grouped.setdefault(m[2], []).append(int(m[1]))
        else:
            rest.append(w)
    lines = []
    for role, nums in grouped.items():
        nums.sort()
        if len(nums) > 2 and nums == list(range(nums[0], nums[-1] + 1)):
            span = f"{len(nums)} pieces (No. {nums[0]:03d}–{nums[-1]:03d})"
        else:
            span = ", ".join(f"{n:03d}" for n in nums)
        lines.append(f"missing {role} photo: {span}")
    return lines + rest


def cmd_catalog(args) -> int:
    brand = load_brand(args.brand)
    catalog = get_source(brand).load()

    print(f"{brand.name}\n{brand.repo_path}")
    if catalog.drop:
        short = {k: v for k, v in catalog.drop.items()
                 if isinstance(v, (str, int)) and len(str(v)) <= 60}
        print("Drop: " + "  ".join(f"{k}={v}" for k, v in short.items()))

    print(f"\n{'NO.':<9}{'NAME':<42}{'H D C':<8}{'BUY':<6}PROVENANCE")
    for p in catalog.pieces:
        marks = " ".join("●" if r in p.photos else "·" for r in PHOTO_ROLES)
        print(f"{p.code:<9}{p.name[:40]:<42}{marks:<8}"
              f"{'yes' if p.buyable else 'no':<6}{'yes' if p.provenance else '—'}")
    print(f"\n{len(catalog.pieces)} pieces")

    lines = summarise_warnings(catalog.warnings)
    if lines:
        print(f"\n{len(lines)} warning(s):")
        for line in lines:
            print(f"  ! {line}")

    return 1 if args.strict and catalog.warnings else 0


def side_by_side(before: Image.Image, after: Image.Image, fill: str) -> Image.Image:
    gap = 24
    canvas = Image.new("RGB", (before.width * 2 + gap, before.height), fill)
    canvas.paste(before, (0, 0))
    canvas.paste(after, (before.width + gap, 0))
    return canvas


def cmd_treat(args) -> int:
    if not args.all and not args.numbers:
        print("press treat: give piece numbers (e.g. 10 11) or --all", file=sys.stderr)
        return 2

    brand = load_brand(args.brand)
    catalog = get_source(brand).load()
    treatment = Treatment.from_brand(brand)
    crops = brand.raw.get("crops") or {}
    width = int(crops.get("width", 1080))

    by_number = {p.number: p for p in catalog.pieces}
    unknown = [n for n in args.numbers if n not in by_number]
    if unknown:
        print(f"press treat: not in catalog: {', '.join(f'{n:03d}' for n in unknown)}", file=sys.stderr)
        return 2
    pieces = catalog.pieces if args.all else [by_number[n] for n in args.numbers]

    out_dir = PROJECT_ROOT / "renders" / ("compare" if args.compare else "treat") / brand.id
    written = 0
    for piece in pieces:
        for role, path in piece.photos.items():
            ratio = parse_ratio(crops.get(role, "4:5"))
            cropped, upscaled = crop_to_ratio(open_srgb(path), ratio, width)
            graded = treatment.apply(cropped, seed=f"{brand.id}:{piece.number:03d}:{role}")
            result = side_by_side(cropped, graded, brand.palette["pitch"]) if args.compare else graded

            out = out_dir / f"{piece.number:03d}-{role}-{ratio[0]}x{ratio[1]}.png"
            save_png(result, out)
            written += 1
            note = "  (upscaled: source smaller than output)" if upscaled else ""
            print(f"{piece.code} {role:<8} -> {out.relative_to(PROJECT_ROOT)}{note}")
        if not piece.photos:
            print(f"{piece.code} no photos, skipped")

    print(f"\n{written} file(s) written")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="press", description="Sets and prints. Never publishes.")
    parser.add_argument("--brand", default="basement-supply")
    sub = parser.add_subparsers(dest="command", required=True)

    cat = sub.add_parser("catalog", help="read the source catalog and report its state")
    cat.add_argument("--strict", action="store_true", help="exit non-zero if there are warnings")
    cat.set_defaults(func=cmd_catalog)

    treat = sub.add_parser("treat", help="apply role crops + post treatment to piece photos")
    treat.add_argument("numbers", nargs="*", type=int, help="piece numbers, e.g. 10 11")
    treat.add_argument("--all", action="store_true", help="every piece in the catalog")
    treat.add_argument("--compare", action="store_true", help="write before|after side by side")
    treat.set_defaults(func=cmd_treat)

    register_card(sub)
    register_posts(sub)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrandError as e:
        print(f"press: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
