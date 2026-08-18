import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# backend/library/catalog.py -> backend/ -> repo root. No Django import here
# on purpose: this module (and matcher.py, which depends on it) should be
# importable and runnable from a bare Python REPL or a standalone script,
# not just from inside the Django app - e.g. a future tuning script that
# sweeps thresholds against labelled data has no reason to need Django
# installed at all.
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "catalog.csv"


@dataclass(frozen=True)
class CatalogEntry:
    id: int
    title: str
    author: str
    alt_titles: tuple[str, ...]
    format: str
    year: str


@lru_cache(maxsize=1)
def load_catalog(path: Path | None = None) -> tuple[CatalogEntry, ...]:
    """Catalog is small (hundreds of rows) and static for the life of the
    process, so a single in-memory tuple beats a DB table + import step.
    `path` is for callers that need a different catalog (tests, a tuning
    script against a labelled subset) - the Django app never passes one."""
    catalog_path = path or DEFAULT_CATALOG_PATH
    with open(catalog_path, newline="", encoding="utf-8") as f:
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
