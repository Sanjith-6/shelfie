import unicodedata
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz

from .catalog import CatalogEntry, load_catalog

# Auto-add only if the top match is this confident...
HIGH_CONFIDENCE_THRESHOLD = 0.90
# ...AND it beats the runner-up by at least this much. A high score with a
# close second place means two catalog entries are both plausible (two
# editions, two books sharing a title) - that's ambiguity, not confidence.
AMBIGUITY_MARGIN = 0.05
# Below this, nothing in the catalog is a real candidate.
REVIEW_FLOOR = 0.55

TITLE_WEIGHT = 0.7
AUTHOR_WEIGHT = 0.3


class MatchStatus(str, Enum):
    AUTO = "auto"
    NEEDS_REVIEW = "needs_review"
    UNMATCHED = "unmatched"


@dataclass
class Candidate:
    entry: CatalogEntry
    score: float


@dataclass
class MatchResult:
    status: MatchStatus
    best: Candidate | None
    candidates: list[Candidate]


def _strip_accents(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_title(s: str) -> str:
    s = _strip_accents(s or "").lower()
    s = " ".join(s.split())
    return s.strip(" .,:;-")


def normalize_author(s: str) -> str:
    """Fold accents, collapse initials, and reorder 'Last, First' to
    'First Last' so catalog inconsistencies don't cost match score."""
    s = _strip_accents(s or "").lower().strip()
    if "," in s:
        last, _, rest = s.partition(",")
        s = f"{rest.strip()} {last.strip()}"
    s = s.replace(".", "")
    return " ".join(s.split())


def _length_ratio_penalty(a: str, b: str) -> float:
    """WRatio alone can score a short title as a near-perfect match against
    a much longer one that simply contains it ("Dune" inside "Dune
    Messiah"), because its partial-match component rewards full
    containment regardless of how much of the longer string is left over.
    This multiplies the raw score down by how unequal the two lengths are,
    so containment alone isn't enough - the strings have to be close in
    length too."""
    if not a or not b:
        return 0.0
    shorter, longer = sorted((len(a), len(b)))
    return shorter / longer


def _title_score(read_title: str, entry: CatalogEntry) -> float:
    read_norm = normalize_title(read_title)
    best = 0.0
    for candidate_title in (entry.title, *entry.alt_titles):
        candidate_norm = normalize_title(candidate_title)
        raw = fuzz.WRatio(read_norm, candidate_norm) / 100
        penalty = _length_ratio_penalty(read_norm, candidate_norm)
        best = max(best, raw * penalty)
    return best


def _author_score(read_author: str, entry: CatalogEntry) -> float | None:
    if not (read_author and read_author.strip() and entry.author):
        # No author read off the spine, or catalog is missing one - don't
        # guess, just fall back to title-only scoring for this entry.
        return None
    score = fuzz.token_sort_ratio(
        normalize_author(read_author), normalize_author(entry.author)
    )
    return score / 100


def _combined_score(read_title: str, read_author: str, entry: CatalogEntry) -> float:
    title_score = _title_score(read_title, entry)
    author_score = _author_score(read_author, entry)
    if author_score is None:
        return title_score
    return TITLE_WEIGHT * title_score + AUTHOR_WEIGHT * author_score


def match(read_title: str, read_author: str = "", top_n: int = 5) -> MatchResult:
    """Score a VLM-read (title, author) against every catalog entry and
    decide whether it's auto-addable, needs human review, or has no
    plausible match at all."""
    scored = [
        Candidate(entry=entry, score=_combined_score(read_title, read_author, entry))
        for entry in load_catalog()
    ]
    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:top_n]

    if not top or top[0].score < REVIEW_FLOOR:
        return MatchResult(status=MatchStatus.UNMATCHED, best=None, candidates=top)

    runner_up = top[1].score if len(top) > 1 else 0.0
    margin = top[0].score - runner_up

    author_read = bool(read_author and read_author.strip())
    if top[0].score >= HIGH_CONFIDENCE_THRESHOLD and margin >= AMBIGUITY_MARGIN and author_read:
        return MatchResult(status=MatchStatus.AUTO, best=top[0], candidates=top)

    return MatchResult(status=MatchStatus.NEEDS_REVIEW, best=top[0], candidates=top)
