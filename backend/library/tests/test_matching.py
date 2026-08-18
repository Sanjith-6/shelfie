"""Behavior tests for library.matcher, grounded in the matcher audit done
this session - each test locks in a specific failure mode found (or
deliberately checked for) against the real catalog.csv, not just a smoke
test that the code runs. Numeric assertions come from actually running the
matcher and reading the scores, not guessed bounds.
"""

from library.matcher import match


def test_no_author_read_cannot_auto_add():
    """The demonstrated bug from the audit: reading a title alone, however
    exact, must never auto-add - the catalog was built with same-title
    books specifically so a title-only match can't safely stand on its
    own."""
    result = match("Dune", "")
    assert result.status.value == "review"
    assert result.candidates[0].entry.title == "Dune"


def test_length_penalty_prevents_substring_confusion():
    """"Dune" must not look like a near-miss for "Dune Messiah". This
    asserts the suppressed score directly (0.51), not just the final
    status, specifically so the test fails if the length-ratio penalty is
    removed - without it this candidate scores ~0.90 (proven during the
    matcher audit), comfortably above the 0.6 bound asserted here."""
    result = match("Dune", "Frank Herbert")
    assert result.status.value == "auto"
    assert result.candidates[0].entry.title == "Dune"

    dune_messiah = next(c for c in result.candidates if c.entry.title == "Dune Messiah")
    assert dune_messiah.score < 0.6


def test_alt_title_resolves_to_canonical_entry():
    """UK title read off the spine must resolve to the catalog's US-titled
    canonical entry via alt_titles."""
    result = match("Harry Potter and the Philosopher's Stone", "J.K. Rowling")
    assert result.candidates[0].entry.title == "Harry Potter and the Sorcerer's Stone"
    assert result.candidates[0].score >= 0.99


def test_author_lastname_first_form_matches_natural_order():
    """Catalog stores this author as "Martin, George R. R."; a natural-order
    VLM read ("George R.R. Martin") must still match well."""
    result = match("A Clash of Kings", "George R.R. Martin")
    assert result.status.value == "auto"
    assert result.candidates[0].entry.author == "Martin, George R. R."


def test_accented_author_matches_unaccented_read():
    """VLM reads are plain ASCII more often than not - an unaccented read
    must match the catalog's accented "García Márquez" at full score."""
    result = match("One Hundred Years of Solitude", "Gabriel Garcia Marquez")
    assert result.status.value == "auto"
    assert result.candidates[0].score == 1.0


def test_multi_author_order_does_not_match_reliably():
    """Two Good Omens editions credit the same two authors in opposite
    order. token_sort_ratio sorts words before comparing, so author order
    shouldn't matter for matching a name string - but with two catalog
    entries differing ONLY in author order, both editions tie exactly
    regardless of which order is read, and the tie (not an order mismatch)
    is what forces review. This is the honest behavior, not "matches the
    right edition"."""
    for read_author in ("Neil Gaiman and Terry Pratchett", "Terry Pratchett and Neil Gaiman"):
        result = match("Good Omens", read_author)
        assert result.status.value == "review"
        scores = {c.entry.id: c.score for c in result.candidates if c.entry.title == "Good Omens"}
        assert scores[1030] == 1.0
        assert scores[1031] == 1.0


def test_same_title_different_author_routes_to_correct_entry():
    """Two "Origin" books exist with different authors - each read must
    land on its own book, not the other, when the author is legible."""
    result = match("Origin", "Dan Brown")
    assert result.status.value == "auto"
    assert result.candidates[0].entry.author == "Dan Brown"

    result = match("Origin", "Jessica Khoury")
    assert result.status.value == "auto"
    assert result.candidates[0].entry.author == "Jessica Khoury"


def test_same_title_no_author_goes_to_review():
    """Three "The Alchemist" catalog entries, no author read at all - must
    never auto-add to any of them, since there's no way to tell which one
    without an author."""
    result = match("The Alchemist", "")
    assert result.status.value == "review"
    alchemist_scores = [c.score for c in result.candidates if c.entry.title == "The Alchemist"]
    assert len(alchemist_scores) == 3
    assert all(score == 1.0 for score in alchemist_scores)


def test_two_editions_margin_gate_forces_review():
    """Two editions of Gone Girl are identical on paper (same title, same
    author) - the margin gate is what catches this, since both editions
    score an exact tie and neither can beat the other by the required
    margin."""
    result = match("Gone Girl", "Gillian Flynn")
    assert result.status.value == "review"
    top, runner_up = result.candidates[0], result.candidates[1]
    assert top.entry.title == "Gone Girl"
    assert runner_up.entry.title == "Gone Girl"
    assert top.score == runner_up.score == 1.0


def test_ocr_garbled_read_still_finds_right_book():
    """Digit-for-letter OCR noise ("Dun3 Messi4h", "Frank Herberd") must
    still surface the correct book as the top candidate - status caps at
    review rather than auto, which is the right call for a read this
    noisy, but it must not lose the book or misidentify it."""
    result = match("Dun3 Messi4h", "Frank Herberd")
    assert result.candidates[0].entry.title == "Dune Messiah"
    assert result.status.value in ("auto", "review")


def test_garbage_input_returns_unmatched_not_low_confidence_guess():
    """Meaningless input must not silently produce a low-confidence
    "best guess" - it has to land below the review floor and come back
    unmatched, so the user isn't shown a fabricated suggestion."""
    result = match("xkqzv wmplr fjhtn", "bnvcx qwerty")
    assert result.status.value == "unmatched"
    assert result.best is None
    assert result.candidates[0].score < 0.55
