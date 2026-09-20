"""`press plan` — what PRESS would post next, and why."""
from __future__ import annotations

import datetime as dt
import sys
from types import SimpleNamespace

from .brand import load_brand
from .cli_post import _guard, cmd_new
from .ledger import Ledger
from .planner import plan
from .sources import get_source


def cmd_plan(args) -> int:
    brand = load_brand(args.brand)
    catalog = get_source(brand).load()
    ledger = Ledger(brand.id)
    plans, notices = plan(brand, catalog, ledger, count=max(1, args.count))

    for n in notices:
        print(f"note: {n}")

    for i, p in enumerate(plans, 1):
        when = dt.date.fromisoformat(p.date)
        subjects = " ".join(f"No. {n:03d}" for n in p.subjects) or "—"
        tag = f"   [arc {p.arc}]" if p.arc else ""
        print(f"\n{i}  {when:%a %Y-%m-%d}  {p.label}  {subjects}{tag}")
        for reason in p.reasons:
            print(f"   - {reason}")
        if p.needs:
            print(f"   - needs your own {'video or file' if p.needs == 'file' else 'photo'}")
        print(f"   {p.command}")

    if not args.take:
        return 0

    top = plans[0]
    if top.needs:
        print(f"\npress plan: this one needs your own {top.needs}; run the command above with a path",
              file=sys.stderr)
        return 1
    print()
    return cmd_new(SimpleNamespace(
        brand=args.brand, format=top.format, numbers=top.subjects, photo=[], file=[],
        ratio=None, date=top.date, note=top.note, arc=top.arc,
    ))


def register_plan(sub) -> None:
    p = sub.add_parser("plan", help="suggest the next post(s), with reasoning")
    p.add_argument("--count", type=int, default=1, help="how many ahead to suggest")
    p.add_argument("--take", action="store_true", help="run the first suggestion now")
    p.set_defaults(func=_guard(cmd_plan))
