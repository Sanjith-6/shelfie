import unicodedata
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz

from .catalog import CatalogEntry, load_catalog

# These five numbers were set by hand, by reasoning about this specific
# catalog and testing them against it - not from labelled data and not from
# a precision/recall sweep. There was no time this session to build a
# labelled test set (real photos, real VLM reads, ground-truth catalog IDs)
# to tune against. Treat them as a defensible starting point, not a
# calibrated result. Tuning against real data is a "given another day" item.
#
# The length-ratio penalty in _length_ratio_penalty() below is deliberately
# aggressive, and that's a decision, not an oversight. It was tested against
# realistic truncated-but-legitimate reads (a VLM reading only the main
# title of a subtitled book, or dropping trailing words) and it does
# sometimes rank the wrong, shorter book above the correct, longer one - two
# of eight test cases did. Softening the curve (sqrt, a floor) was tried and
# doesn't fix it: the raw fuzzy-match score is what's actually ambiguous
# between "genuine truncation of the right book" and "coincidentally similar
# wrong book" at that point, not the length penalty's shape. A read of
# "Dune" is genuinely indistinguishable from a truncated read of "Dune
# Messiah" - the information needed to tell them apart isn't present in the
# text, so no scoring function can recover it. That ambiguity belongs with
# the human reviewer, not something to be scored around. The mitigation is
# the review/unmatched path, not a better formula - a wrong top-ranked
# candidate has been verified to never reach AUTO (see
# test_length_penalty_prevents_substring_confusion and the audit that
# preceded it), so the failure mode this trades into is "needs a human to
# confirm or search manually," never a silent wrong add.

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
    NEEDS_REVIEW = "review"
    UNMATCHED = "unmatched"


@dataclass
class Candidate:
    entry: CatalogEntry
    score: float
    reasons: list[str]


@dataclass
class MatchResult:
    status: MatchStatus
    best: Candidate | None
    candidates: list[Candidate]


def _strip_accents(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_LEADING_ARTICLES = ("the ", "a ", "an ")


def normalize_title(s: str) -> str:
    s = _strip_accents(s or "").casefold()
    s = " ".join(s.split())
    s = s.strip(" .,:;-")
    for article in _LEADING_ARTICLES:
        if s.startswith(article):
            s = s[len(article):]
            break
    return s


def normalize_author(s: str) -> str:
    """Fold accents, collapse initials, and reorder 'Last, First' to
    'First Last' so catalog inconsistencies don't cost match score."""
    s = _strip_accents(s or "").casefold().strip()
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


def _title_variants(s: str) -> list[str]:
    """A title's normalized form, plus - if it has a subtitle after a colon
    - the main title alone as a second form. Both are scored; keeping the
    full form matters too, since a read that includes the subtitle should
    still get credit for it."""
    variants = [normalize_title(s)]
    if ":" in s:
        main_title = normalize_title(s.split(":", 1)[0])
        if main_title and main_title not in variants:
            variants.append(main_title)
    return variants


def _title_score(read_title: str, entry: CatalogEntry) -> tuple[float, bool]:
    """Returns (score, matched_via_alt_title) - the second value is only
    for building an honest reason string, not used in scoring itself."""
    read_variants = _title_variants(read_title)
    best = 0.0
    matched_via_alt = False
    for candidate_title in (entry.title, *entry.alt_titles):
        for candidate_variant in _title_variants(candidate_title):
            for read_variant in read_variants:
                raw = fuzz.WRatio(read_variant, candidate_variant) / 100
                penalty = _length_ratio_penalty(read_variant, candidate_variant)
                score = raw * penalty
                if score > best:
                    best = score
                    matched_via_alt = candidate_title != entry.title
    return best, matched_via_alt


def _author_score(read_author: str, entry: CatalogEntry) -> float | None:
    if not (read_author and read_author.strip() and entry.author):
        # No author read off the spine, or catalog is missing one - don't
        # guess, just fall back to title-only scoring for this entry.
        return None
    score = fuzz.token_sort_ratio(
        normalize_author(read_author), normalize_author(entry.author)
    )
    return score / 100


def _score_entry(read_title: str, read_author: str, entry: CatalogEntry) -> tuple[float, list[str]]:
    """Score one catalog entry against a VLM read and explain, in plain
    words, why - these reasons are shown to the user in the review UI, so
    they describe what actually happened in this function, not a vibe."""
    title_score, matched_via_alt = _title_score(read_title, entry)
    author_score = _author_score(read_author, entry)

    reasons = []
    if title_score >= 0.99:
        reasons.append("matched an alternate title" if matched_via_alt else "exact title match")
    elif title_score >= HIGH_CONFIDENCE_THRESHOLD:
        reasons.append("close title match")
    elif title_score >= REVIEW_FLOOR:
        reasons.append("partial title match")
    else:
        reasons.append("title does not match well")

    if author_score is None:
        reasons.append("no author was read off the spine")
        return title_score, reasons

    if author_score >= 0.99:
        reasons.append("exact author match")
    elif author_score >= HIGH_CONFIDENCE_THRESHOLD:
        reasons.append("close author match")
    else:
        reasons.append("author does not match well")

    combined = TITLE_WEIGHT * title_score + AUTHOR_WEIGHT * author_score
    return combined, reasons


def match(read_title: str, read_author: str = "", top_n: int = 5) -> MatchResult:
    """Score a VLM-read (title, author) against every catalog entry and
    decide whether it's auto-addable, needs human review, or has no
    plausible match at all."""
    scored = []
    for entry in load_catalog():
        score, reasons = _score_entry(read_title, read_author, entry)
        scored.append(Candidate(entry=entry, score=score, reasons=reasons))
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
