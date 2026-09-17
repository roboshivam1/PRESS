from .base import PHOTO_ROLES, Catalog, Piece, Source


def get_source(brand) -> Source:
    if brand.adapter == "basement_supply":
        from .basement_supply import BasementSupplySource
        return BasementSupplySource(brand.repo_path)
    raise ValueError(f"unknown source adapter: {brand.adapter}")


__all__ = ["PHOTO_ROLES", "Catalog", "Piece", "Source", "get_source"]
