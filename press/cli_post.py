"""Post commands. PRESS makes; Shivam says."""
from __future__ import annotations

import datetime as dt
import shutil
import sys
from pathlib import Path

from .brand import PROJECT_ROOT, load_brand
from .compose.render import RenderError
from .compose.specimen_card import CardError
from .ledger import Ledger, LedgerError, Record, sha256
from .posts import PostError, build_assets, format_config, outbox_dir
from .sources import get_source

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="minutes")


def parse_date(value: str) -> str:
    v = value.strip().lower()
    today = dt.date.today()
    if v in ("", "none"):
        return ""
    if v == "today":
        return today.isoformat()
    if v == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    if len(v) >= 3:
        for i, day in enumerate(WEEKDAYS):
            if day.startswith(v):
                ahead = (i - today.weekday()) % 7 or 7
                return (today + dt.timedelta(days=ahead)).isoformat()
    try:
        return dt.date.fromisoformat(v).isoformat()
    except ValueError:
        raise LedgerError(f"can't read date '{value}': use YYYY-MM-DD, today, tomorrow, or a weekday") from None


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def cmd_new(args) -> int:
    brand = load_brand(args.brand)
    key, fmt = format_config(brand, args.format)
    date = parse_date(args.date or "")
    catalog = get_source(brand).load()
    ledger = Ledger(brand.id)

    by_number = {p.number: p for p in catalog.pieces}
    unknown = [n for n in args.numbers if n not in by_number]
    if unknown:
        raise PostError(f"not in catalog: {', '.join(f'{n:03d}' for n in unknown)}")
    pieces = [by_number[n] for n in args.numbers]

    for p in pieces:
        last = ledger.last_featured(p.number)
        if last:
            print(f"note: {p.code} was last in {last.code} ({last.format}, "
                  f"{last.date or 'unscheduled'}, {last.status})")

    post_id = ledger.next_id()
    post_dir = PROJECT_ROOT / "posts" / brand.id / f"{post_id:03d}"
    if post_dir.exists():
        raise PostError(f"{rel(post_dir)} already exists with no ledger record; remove it first")

    try:
        paths = build_assets(brand, catalog, key, fmt, pieces,
                             [Path(p).expanduser() for p in args.photo],
                             [Path(f).expanduser() for f in args.file],
                             args.ratio, post_dir)
    except BaseException:
        shutil.rmtree(post_dir, ignore_errors=True)
        raise

    record = Record(
        id=post_id, brand=brand.id, format=key, subjects=[p.number for p in pieces],
        date=date, notes=args.note or "", arc=getattr(args, "arc", "") or "", created=now(),
        assets=[{"path": rel(p), "sha256": sha256(p)} for p in paths],
    )
    path = ledger.save(record)

    subjects = " ".join(p.code for p in pieces)
    print(f"\n{record.code} — {key.replace('_', ' ').title()}"
          f"{' — ' + subjects if subjects else ''} — {date or 'unscheduled'}  [draft]")
    for a in record.assets:
        print(f"  {a['path']}")
    print(f"\nwrite the caption in {rel(path)}, then: press approve {post_id}")
    return 0


def cmd_ledger(args) -> int:
    brand = load_brand(args.brand)
    ledger = Ledger(brand.id)

    if args.id is not None:
        r = ledger.get(args.id)
        print(f"{r.code}  {r.format}  [{r.status}]")
        print(f"date      {r.date or 'unscheduled'}")
        print(f"subjects  {', '.join(f'No. {n:03d}' for n in r.subjects) or '—'}")
        for a in r.assets:
            print(f"asset     {a['path']}")
        for label, value in (("permalink", r.permalink), ("notes", r.notes)):
            if value:
                print(f"{label:<10}{value}")
        print("\n" + (r.caption or "(no caption yet)"))
        print(f"\nfile: {rel(ledger.path(r.id))}")
        return 0

    records = ledger.all()
    if not records:
        print("ledger is empty")
        return 0
    print(f"{'POST':<6}{'DATE':<13}{'FORMAT':<15}{'SUBJECTS':<16}{'STATUS':<10}CAPTION")
    for r in records:
        subjects = " ".join(f"{n:03d}" for n in r.subjects) or "—"
        print(f"{r.id:03d}   {(r.date or 'unscheduled'):<13}{r.format:<15}{subjects[:15]:<16}"
              f"{r.status:<10}{'yes' if r.caption else '—'}")
    return 0


def cmd_approve(args) -> int:
    brand = load_brand(args.brand)
    ledger = Ledger(brand.id)
    r = ledger.get(args.id)

    if r.status != "draft":
        raise LedgerError(f"{r.code} is {r.status}; only drafts can be approved")
    if not r.caption:
        raise LedgerError(f"{r.code} has no caption; write it in {rel(ledger.path(r.id))} first")
    if not r.assets:
        raise LedgerError(f"{r.code} has no assets")
    for a in r.assets:
        src = PROJECT_ROOT / a["path"]
        if not src.is_file():
            raise LedgerError(f"asset missing: {a['path']}")
        if sha256(src) != a["sha256"]:
            raise LedgerError(f"asset changed since the draft was made: {a['path']}")

    dest = outbox_dir(brand, r)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for a in r.assets:
        shutil.copy2(PROJECT_ROOT / a["path"], dest / Path(a["path"]).name)
    (dest / "caption.txt").write_text(r.caption + "\n", encoding="utf-8")

    r.status, r.approved = "approved", now()
    ledger.save(r)
    print(f"{r.code} approved -> {rel(dest)}")
    return 0


def cmd_reopen(args) -> int:
    brand = load_brand(args.brand)
    ledger = Ledger(brand.id)
    r = ledger.get(args.id)
    if r.status != "approved":
        raise LedgerError(f"{r.code} is {r.status}; only approved posts can be reopened")
    shutil.rmtree(outbox_dir(brand, r), ignore_errors=True)
    r.status, r.approved = "draft", ""
    ledger.save(r)
    print(f"{r.code} back to draft; outbox copy removed")
    return 0


def cmd_posted(args) -> int:
    brand = load_brand(args.brand)
    ledger = Ledger(brand.id)
    r = ledger.get(args.id)
    if r.status != "approved":
        raise LedgerError(f"{r.code} is {r.status}; approve it before marking it posted")
    if not args.permalink.startswith(("https://", "http://")):
        raise LedgerError("permalink should be a full URL")
    shutil.rmtree(outbox_dir(brand, r), ignore_errors=True)
    r.status, r.permalink, r.posted = "posted", args.permalink, now()
    ledger.save(r)
    print(f"{r.code} closed: {r.permalink}")
    return 0


def cmd_drop(args) -> int:
    brand = load_brand(args.brand)
    ledger = Ledger(brand.id)
    r = ledger.get(args.id)
    if r.status == "posted":
        raise LedgerError(f"{r.code} is already posted; the ledger keeps it")
    shutil.rmtree(outbox_dir(brand, r), ignore_errors=True)
    r.status = "dropped"
    ledger.save(r)
    print(f"{r.code} dropped")
    return 0


def _guard(fn):
    def run(args):
        try:
            return fn(args)
        except (LedgerError, PostError, CardError, RenderError) as e:
            print(f"press: {e}", file=sys.stderr)
            return 1
    return run


def register_posts(sub) -> None:
    new = sub.add_parser("new", help="render a post and write a draft record")
    new.add_argument("format", help="e.g. ledge, specimen-card, bench, failure, field-report, placement")
    new.add_argument("numbers", nargs="*", type=int, help="catalog piece numbers")
    new.add_argument("--photo", action="append", default=[], help="source photo, repeat in carousel order")
    new.add_argument("--file", action="append", default=[], help="file copied as-is, e.g. a video")
    new.add_argument("--ratio", help="override the format's ratio, e.g. 1:1")
    new.add_argument("--date", help="YYYY-MM-DD, today, tomorrow, or a weekday")
    new.add_argument("--note", help="free-text note on the record")
    new.add_argument("--arc", default="", help="drop-arc tag, e.g. drop-01:3")
    new.set_defaults(func=_guard(cmd_new))

    led = sub.add_parser("ledger", help="list posts, or show one")
    led.add_argument("id", nargs="?", type=int)
    led.set_defaults(func=_guard(cmd_ledger))

    for name, fn, text in (("approve", cmd_approve, "approve a draft into the outbox"),
                           ("reopen", cmd_reopen, "send an approved post back to draft"),
                           ("drop", cmd_drop, "abandon a post")):
        p = sub.add_parser(name, help=text)
        p.add_argument("id", type=int)
        p.set_defaults(func=_guard(fn))

    posted = sub.add_parser("posted", help="close a record with its permalink")
    posted.add_argument("id", type=int)
    posted.add_argument("permalink")
    posted.set_defaults(func=_guard(cmd_posted))
