"""The shapes every source adapter returns. The rest of PRESS only sees these."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

PHOTO_ROLES = ("hero", "detail", "context")


@dataclass(frozen=True)
class Piece:
    number: int
    slug: str
    name: str
    series: str
    provenance: str
    specs: dict
    photos: dict[str, Path]  # role -> path; missing roles are simply absent
    payment_link: str
    status: str

    @property
    def code(self) -> str:
        return f"No. {self.number:03d}"

    @property
    def buyable(self) -> bool:
        return bool(self.payment_link)

    @property
    def missing_photos(self) -> list[str]:
        return [r for r in PHOTO_ROLES if r not in self.photos]


@dataclass
class Catalog:
    pieces: list[Piece]
    drop: dict
    warnings: list[str] = field(default_factory=list)


class Source(Protocol):
    def load(self) -> Catalog: ...
