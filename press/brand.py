"""Brand config: loads brands/<id>.toml into a validated Brand."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = PROJECT_ROOT / "brands"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandError(Exception):
    pass


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    tagline: str
    adapter: str
    repo_path: Path
    palette: dict[str, str]
    raw: dict = field(repr=False, default_factory=dict)


def load_brand(brand_id: str) -> Brand:
    path = BRANDS_DIR / f"{brand_id}.toml"
    if not path.is_file():
        available = sorted(p.stem for p in BRANDS_DIR.glob("*.toml"))
        raise BrandError(
            f"no brand config at {path} (available: {', '.join(available) or 'none'})"
        )

    with path.open("rb") as f:
        data = tomllib.load(f)

    try:
        b, s = data["brand"], data["source"]
        brand = Brand(
            id=b["id"],
            name=b["name"],
            tagline=b.get("tagline", ""),
            adapter=s["adapter"],
            repo_path=Path(s["repo_path"]).expanduser(),
            palette=dict(data["palette"]),
            raw=data,
        )
    except KeyError as e:
        raise BrandError(f"{path.name}: missing required key {e}") from None

    if brand.id != brand_id:
        raise BrandError(f"{path.name}: brand.id is '{brand.id}', expected '{brand_id}'")

    bad = [k for k, v in brand.palette.items() if not HEX.match(str(v))]
    if bad:
        raise BrandError(f"{path.name}: invalid hex for palette token(s): {', '.join(bad)}")

    if not brand.repo_path.is_dir():
        raise BrandError(f"{path.name}: repo_path does not exist: {brand.repo_path}")

    return brand
