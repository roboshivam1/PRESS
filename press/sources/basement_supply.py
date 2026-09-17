"""Read-only adapter for the Basement Supply site repo.

Mirrors the site's own conventions:
  products  content/products/*.yaml   (top level only, so _archive/ is never seen)
  defaults  PRODUCT_DEFAULTS < SERIES_DEFAULTS[series] < product YAML
  photos    static/img/products/NNN/{hero,detail,context}.{jpg,jpeg,png,webp}, first match wins
Never writes to the repo, including __pycache__.
"""
from __future__ import annotations

import csv
import runpy
import sys
from pathlib import Path

import yaml

from .base import PHOTO_ROLES, Catalog, Piece

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
IDENTITY_KEYS = {"number", "slug", "name", "series", "provenance", "payment_link", "status"}


class BasementSupplySource:
    def __init__(self, repo: Path):
        self.repo = repo
        self.products_dir = repo / "content" / "products"
        self.images_dir = repo / "static" / "img" / "products"
        self.manifest_path = repo / "content" / "manifest.tsv"

    def load(self) -> Catalog:
        warnings: list[str] = []
        config = self._read_config(warnings)
        product_defaults = dict(config.get("PRODUCT_DEFAULTS") or {})
        series_defaults = config.get("SERIES_DEFAULTS") or {}

        pieces = []
        for path in sorted(self.products_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            piece = self._read_piece(path, product_defaults, series_defaults, warnings)
            if piece:
                pieces.append(piece)

        pieces.sort(key=lambda p: p.number)
        self._check_numbers(pieces, warnings)
        self._cross_check_manifest(pieces, warnings)
        return Catalog(pieces=pieces, drop=dict(config.get("CURRENT_DROP") or {}), warnings=warnings)

    def _read_config(self, warnings: list[str]) -> dict:
        path = self.repo / "config.py"
        if not path.is_file():
            warnings.append("config.py not found; no defaults applied")
            return {}
        repo_str, old_bytecode = str(self.repo), sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.path.insert(0, repo_str)
        try:
            return runpy.run_path(str(path))
        except Exception as e:
            warnings.append(f"config.py failed to load ({type(e).__name__}: {e}); no defaults applied")
            return {}
        finally:
            sys.path.remove(repo_str)
            sys.dont_write_bytecode = old_bytecode

    def _read_piece(self, path, product_defaults, series_defaults, warnings) -> Piece | None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            warnings.append(f"{path.name}: invalid YAML ({e})")
            return None
        if not isinstance(data, dict) or "number" not in data:
            warnings.append(f"{path.name}: no 'number' field, skipped")
            return None

        series = str(data.get("series") or "")
        merged = dict(product_defaults)
        if isinstance(series_defaults, dict) and isinstance(series_defaults.get(series), dict):
            merged.update(series_defaults[series])
        merged.update(data)

        try:
            number = int(merged["number"])
        except (TypeError, ValueError):
            warnings.append(f"{path.name}: number '{merged['number']}' is not an integer, skipped")
            return None

        piece = Piece(
            number=number,
            slug=str(merged.get("slug") or path.stem),
            name=str(merged.get("name") or "").strip(),
            series=series,
            provenance=str(merged.get("provenance") or "").strip(),
            specs={k: v for k, v in merged.items() if k not in IDENTITY_KEYS},
            photos=self._find_photos(number),
            payment_link=str(merged.get("payment_link") or "").strip(),
            status=str(merged.get("status") or ""),
        )
        for role in piece.missing_photos:
            warnings.append(f"{piece.code}: missing {role} photo")
        return piece

    def _find_photos(self, number: int) -> dict[str, Path]:
        folder = self.images_dir / f"{number:03d}"
        found: dict[str, Path] = {}
        if not folder.is_dir():
            return found
        for role in PHOTO_ROLES:
            for ext in PHOTO_EXTS:
                candidate = folder / f"{role}{ext}"
                if candidate.is_file():
                    found[role] = candidate
                    break
        return found

    def _check_numbers(self, pieces: list[Piece], warnings: list[str]) -> None:
        seen: dict[int, str] = {}
        for p in pieces:
            if p.number in seen:
                warnings.append(f"{p.code}: duplicate number ({seen[p.number]} and {p.slug})")
            seen.setdefault(p.number, p.slug)

    def _cross_check_manifest(self, pieces: list[Piece], warnings: list[str]) -> None:
        if not self.manifest_path.is_file():
            warnings.append("content/manifest.tsv not found; skipped cross-check")
            return
        manifest: dict[int, str] = {}
        with self.manifest_path.open(newline="", encoding="utf-8") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                if not row or row[0].strip().startswith("#"):
                    continue
                try:
                    number = int(row[0])
                except ValueError:
                    continue  # header row
                manifest[number] = row[2].strip() if len(row) > 2 else ""

        by_number = {p.number: p for p in pieces}
        for n in sorted(set(manifest) - set(by_number)):
            warnings.append(f"No. {n:03d}: in manifest.tsv but has no product YAML")
        for n in sorted(set(by_number) - set(manifest)):
            warnings.append(f"No. {n:03d}: has a product YAML but is not in manifest.tsv")
        for n in sorted(set(manifest) & set(by_number)):
            if manifest[n] and manifest[n] != by_number[n].name:
                warnings.append(
                    f"No. {n:03d}: name differs (manifest '{manifest[n]}' vs YAML '{by_number[n].name}')"
                )
