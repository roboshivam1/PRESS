"""Ledger: one YAML file per post, plain files in git. Not a database."""
from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .brand import PROJECT_ROOT

STATUSES = ("draft", "approved", "posted", "dropped")
FILE = re.compile(r"^post-(\d{3,})\.yaml$")
TEXT_FIELDS = ("brand", "format", "date", "status", "caption", "permalink", "notes",
               "created", "approved", "posted", "arc")


class LedgerError(Exception):
    pass


@dataclass
class Record:
    id: int
    brand: str
    format: str
    subjects: list[int]
    date: str = ""              # target date YYYY-MM-DD; "" = unscheduled
    status: str = "draft"
    caption: str = ""
    assets: list[dict] = field(default_factory=list)   # [{path, sha256}]
    permalink: str = ""
    notes: str = ""
    arc: str = ""
    created: str = ""
    approved: str = ""
    posted: str = ""

    @property
    def code(self) -> str:
        return f"Post {self.id:03d}"


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Ledger:
    def __init__(self, brand_id: str):
        self.brand_id = brand_id
        self.dir = PROJECT_ROOT / "ledger" / brand_id

    def path(self, post_id: int) -> Path:
        return self.dir / f"post-{post_id:03d}.yaml"

    def all(self) -> list[Record]:
        if not self.dir.is_dir():
            return []
        records = [self._read(p) for p in self.dir.glob("post-*.yaml") if FILE.match(p.name)]
        return sorted(records, key=lambda r: r.id)

    def get(self, post_id: int) -> Record:
        path = self.path(post_id)
        if not path.is_file():
            raise LedgerError(f"no record for post {post_id:03d}")
        return self._read(path)

    def next_id(self) -> int:
        records = self.all()
        return records[-1].id + 1 if records else 1

    def last_featured(self, number: int) -> Record | None:
        for r in reversed(self.all()):
            if r.status != "dropped" and number in r.subjects:
                return r
        return None

    def save(self, record: Record) -> Path:
        record.caption = "\n".join(line.rstrip() for line in record.caption.strip().splitlines())
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path(record.id)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            yaml.dump(asdict(record), Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000),
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def _read(self, path: Path) -> Record:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise LedgerError(f"{path.name}: invalid YAML ({e})") from None
        if not isinstance(data, dict):
            raise LedgerError(f"{path.name}: expected a mapping")

        known = {f.name for f in dataclasses.fields(Record)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise LedgerError(f"{path.name}: unknown field(s): {', '.join(unknown)}")
        try:
            record = Record(**data)
        except TypeError as e:
            raise LedgerError(f"{path.name}: {e}") from None

        for name in TEXT_FIELDS:
            value = getattr(record, name)
            setattr(record, name, "" if value is None else str(value))
        record.caption = record.caption.strip()
        record.subjects = [int(n) for n in (record.subjects or [])]
        record.assets = list(record.assets or [])

        if record.status not in STATUSES:
            raise LedgerError(f"{path.name}: status '{record.status}' is not one of {', '.join(STATUSES)}")
        return record
