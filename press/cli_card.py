"""`press card` — render Specimen Cards."""
from __future__ import annotations

import sys

from .brand import PROJECT_ROOT, load_brand
from .compose.render import Renderer, RenderError
from .compose.specimen_card import MODES, CardError, card_config, render_card
from .compose.treatment import save_png
from .sources import get_source


def cmd_card(args) -> int:
    if not args.all and not args.numbers:
        print("press card: give piece numbers (e.g. 10 5) or --all", file=sys.stderr)
        return 2

    brand = load_brand(args.brand)
    catalog = get_source(brand).load()
    cfg = card_config(brand)
    modes = MODES if args.mode == "both" else (args.mode or cfg["mode"],)

    by_number = {p.number: p for p in catalog.pieces}
    unknown = [n for n in args.numbers if n not in by_number]
    if unknown:
        print(f"press card: not in catalog: {', '.join(f'{n:03d}' for n in unknown)}", file=sys.stderr)
        return 2
    pieces = catalog.pieces if args.all else [by_number[n] for n in args.numbers]

    out_dir = PROJECT_ROOT / "renders" / "cards" / brand.id
    written = 0
    try:
        with Renderer() as renderer:
            for piece in pieces:
                for mode in modes:
                    stem = f"{piece.number:03d}-specimen-{mode}"
                    html_out = out_dir / f"{stem}.html" if args.html else None
                    try:
                        card = render_card(brand, piece, catalog.drop, renderer, mode, html_out)
                    except CardError as e:
                        print(f"{piece.code} skipped: {e}")
                        continue
                    out = out_dir / f"{stem}.png"
                    save_png(card, out)
                    written += 1
                    print(f"{piece.code} {mode:<8} -> {out.relative_to(PROJECT_ROOT)}")
    except RenderError as e:
        print(f"press card: {e}", file=sys.stderr)
        return 1

    print(f"\n{written} card(s) written")
    return 0


def register_card(sub) -> None:
    card = sub.add_parser("card", help="render Specimen Cards")
    card.add_argument("numbers", nargs="*", type=int, help="piece numbers, e.g. 10 5")
    card.add_argument("--all", action="store_true", help="every piece in the catalog")
    card.add_argument("--mode", choices=[*MODES, "both"], help="override the brand's card mode")
    card.add_argument("--html", action="store_true", help="also write the filled HTML, for tuning in a browser")
    card.set_defaults(func=cmd_card)
