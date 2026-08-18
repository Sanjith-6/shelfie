import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

CATALOG_PATH = Path(settings.BASE_DIR).parent / "catalog.csv"


@dataclass(frozen=True)
class CatalogEntry:
    id: int
    title: str
    author: str
    alt_titles: tuple[str, ...]
    format: str
    year: str


@lru_cache(maxsize=1)
def load_catalog() -> tuple[CatalogEntry, ...]:
    """Catalog is small (hundreds of rows) and static for the life of the
    process, so a single in-memory tuple beats a DB table + import step."""
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        entries = []
        for row in reader:
            alt_titles = tuple(
                t.strip() for t in row["alt_titles"].split(";") if t.strip()
            )
            entries.append(
                CatalogEntry(
                    id=int(row["id"]),
                    title=row["title"].strip(),
                    author=row["author"].strip(),
                    alt_titles=alt_titles,
                    format=row["format"].strip(),
                    year=row["year"].strip(),
                )
            )
    return tuple(entries)
