"""Planner: rules only, no model call. Suggests the next post; never decides."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .brand import BrandError
from .posts import format_config

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass
class Plan:
    format: str
    subjects: list[int]
    date: str
    reasons: list[str] = field(default_factory=list)
    arc: str = ""
    needs: str = ""      # "photo", "file", or "" when PRESS can render it alone
    note: str = ""

    @property
    def label(self) -> str:
        return self.format.replace("_", " ").title()

    @property
    def command(self) -> str:
        parts = ["press new", self.format.replace("_", "-")]
        parts += [str(n) for n in self.subjects]
        if self.needs:
            parts.append(f"--{self.needs} PATH")
        parts += ["--date", self.date]
        if self.arc:
            parts += ["--arc", self.arc]
        if self.note:
            parts += ["--note", f'"{self.note}"']
        return " ".join(parts)


def cadence_config(brand) -> dict:
    c = brand.raw.get("cadence") or {}
    days = []
    for d in c.get("days", ["tuesday", "friday"]):
        name = str(d).strip().lower()
        if name not in WEEKDAYS:
            raise BrandError(f"cadence.days: '{d}' is not a weekday")
        days.append(WEEKDAYS.index(name))
    if not days:
        raise BrandError("cadence.days is empty")
    rotation = [str(f).strip().replace("-", "_").lower() for f in c.get("rotation", [])]
    if not rotation:
        raise BrandError("cadence.rotation is empty")
    for name in rotation:
        format_config(brand, name)  # fails loudly on a typo
    return {
        "days": sorted(set(days)),
        "rotation": rotation,
        "cooldown": max(0, int(c.get("cooldown_posts", 6))),
        "arc": dict(c.get("drop_arc") or {}),
    }


def next_slot(days: list[int], after: dt.date) -> dt.date:
    for i in range(1, 15):
        day = after + dt.timedelta(days=i)
        if day.weekday() in days:
            return day
    raise BrandError("cadence.days has no usable weekday")


def subject_role(brand, fmt: dict) -> str | None:
    if fmt["source"] == "piece":
        return str(fmt.get("role", "hero"))
    if fmt["source"] == "card":
        from .compose.specimen_card import card_config
        return card_config(brand)["photo_role"]
    return None


def next_format(brand, cadence: dict, history: list[tuple[str, list[int]]]):
    rotation = cadence["rotation"]
    for name, _ in reversed(history):
        if name in rotation:
            nxt = rotation[(rotation.index(name) + 1) % len(rotation)]
            key, fmt = format_config(brand, nxt)
            return key, fmt, (f"rotation: last was {name.replace('_', ' ')}, "
                              f"{nxt.replace('_', ' ')} is next")
    key, fmt = format_config(brand, rotation[0])
    return key, fmt, f"rotation starts at {rotation[0].replace('_', ' ')} (nothing in the ledger yet)"


def pick_subjects(catalog, history, count: int, cooldown: int, role: str | None):
    if count <= 0:
        return [], []
    usable = [p for p in catalog.pieces if role is None or role in p.photos]
    if not usable:
        return [], [f"no piece has a {role} photo"]

    recent: set[int] = set()
    for _, subjects in history[-cooldown:] if cooldown else []:
        recent.update(subjects)
    last_seen: dict[int, int] = {}
    for i, (_, subjects) in enumerate(history):
        for n in subjects:
            last_seen[n] = i

    fresh = [p.number for p in usable if p.number not in recent]
    pool = fresh or [p.number for p in usable]
    pool.sort(key=lambda n: (last_seen.get(n, -1), n))
    chosen = pool[:count]

    reasons = []
    if not fresh and history:
        reasons.append(f"every piece appeared in the last {cooldown} posts; taking the oldest")
    never = [n for n in chosen if n not in last_seen]
    if never:
        reasons.append("never featured: " + ", ".join(f"No. {n:03d}" for n in never))
    seen = [n for n in chosen if n in last_seen]
    if seen:
        reasons.append("least recently featured: " + ", ".join(f"No. {n:03d}" for n in seen))
    if len(chosen) < count:
        reasons.append(f"only {len(chosen)} piece(s) available, wanted {count}")
    return chosen, reasons


def _arc_code(catalog) -> str:
    code = str(catalog.drop.get("code") or "drop").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", code).strip("-") or "drop"


def pending_arc(cadence: dict, catalog, ledger, today: dt.date):
    arc = cadence["arc"]
    if not arc.get("enabled"):
        return [], ""
    raw = str(arc.get("launch", "")).strip()
    if not raw:
        return [], "drop arc is on but cadence.drop_arc.launch is blank; using the weekly rotation"
    try:
        launch = dt.date.fromisoformat(raw)
    except ValueError:
        raise BrandError("cadence.drop_arc.launch must be YYYY-MM-DD") from None
    if launch < today:
        return [], f"drop arc launch ({launch}) has passed; using the weekly rotation"

    code = _arc_code(catalog)
    done = {r.arc for r in ledger.all() if r.arc}
    steps = []
    for i, step in enumerate(arc.get("sequence", []), 1):
        tag = f"{code}:{i}"
        if tag not in done:
            steps.append((tag, launch - dt.timedelta(days=int(step.get("days_before", 0))), step))
    steps.sort(key=lambda s: s[1])
    return steps, ""


def plan(brand, catalog, ledger, count: int = 1, today: dt.date | None = None):
    cadence = cadence_config(brand)
    today = today or dt.date.today()
    records = [r for r in ledger.all() if r.status != "dropped"]
    history = [(r.format, list(r.subjects)) for r in records]
    dates = [dt.date.fromisoformat(r.date) for r in records if r.date]
    cursor = max([today - dt.timedelta(days=1)] + dates)

    steps, notice = pending_arc(cadence, catalog, ledger, today)
    notices = [notice] if notice else []
    if steps:
        notices.append(f"drop arc active: {len(steps)} step(s) left, rotation paused")

    plans: list[Plan] = []
    while len(plans) < count:
        reasons: list[str] = []
        if steps:
            tag, when, step = steps.pop(0)
            key, fmt = format_config(brand, str(step.get("format", "")))
            subject_count = int(step.get("count", 1))
            note = str(step.get("note", ""))
            reasons.append(f"drop arc: {step.get('days_before', 0)} day(s) before launch")
            if when < today:
                reasons.append(f"scheduled for {when}, which has passed; moved to today")
                when = today
        else:
            tag, note = "", ""
            key, fmt, why = next_format(brand, cadence, history)
            reasons.append(why)
            subject_count = 1
            cursor = next_slot(cadence["days"], cursor)
            when = cursor

        subjects, why = pick_subjects(catalog, history, subject_count,
                                      cadence["cooldown"], subject_role(brand, fmt))
        reasons += why
        source = fmt["source"]
        plans.append(Plan(
            format=key, subjects=subjects, date=when.isoformat(), reasons=reasons, arc=tag,
            needs=source if source in ("photo", "file") else "", note=note,
        ))
        history.append((key, subjects))
        cursor = max(cursor, when)

    return plans, notices
