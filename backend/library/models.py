from django.db import models


class CatalogBook(models.Model):
    """A canonical entry from catalog.csv. id matches the catalog.csv id
    column exactly, so a matcher.py match's catalog_id resolves here with no
    translation - loaded by a management command in a later session."""

    id = models.IntegerField(primary_key=True)
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300)
    alt_titles = models.TextField(blank=True)  # semicolon-separated, as in the CSV
    format = models.CharField(max_length=100, blank=True)
    year = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.title} ({self.author})"


class LibraryEntry(models.Model):
    """A book confirmed into the user's library.

    Scans are stateless (photo in, candidates out) - nothing about a scan
    is persisted until the user confirms a candidate here, so this is the
    only durable table the app needs for the library itself.
    """

    RESOLUTION_CHOICES = [
        ("auto", "Auto-added (high confidence)"),
        ("confirmed", "Confirmed as suggested"),
        ("corrected", "User corrected the suggestion"),
        ("manual", "Entered manually, no catalog match"),
    ]

    catalog_book = models.ForeignKey(
        CatalogBook,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="library_entries",
    )
    # Final values as confirmed by the user - the source of truth for
    # display, whether they came from the catalog match, a correction, or a
    # fully manual entry (where catalog_book is null).
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300, blank=True)
    # What the VLM originally read off the spine, kept for audit even after
    # a correction. Blank for manual entries that never went through a scan.
    raw_title = models.CharField(max_length=500, blank=True)
    raw_author = models.CharField(max_length=300, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    resolution = models.CharField(max_length=10, choices=RESOLUTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.author})"
