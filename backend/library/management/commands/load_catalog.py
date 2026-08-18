from django.core.management.base import BaseCommand

from library.catalog import load_catalog
from library.models import CatalogBook


class Command(BaseCommand):
    help = (
        "Load catalog.csv into the CatalogBook table. Upserts by id, so it's "
        "safe to rerun after editing catalog.csv - a skip-if-any-rows check "
        "would silently do nothing on an edited catalog, which is worse than "
        "just upserting every time."
    )

    def handle(self, *args, **options):
        entries = load_catalog()

        created = updated = unchanged = 0
        for entry in entries:
            defaults = {
                "title": entry.title,
                "author": entry.author,
                "alt_titles": "; ".join(entry.alt_titles),
                "format": entry.format,
                "year": entry.year,
            }
            book, was_created = CatalogBook.objects.get_or_create(id=entry.id, defaults=defaults)
            if was_created:
                created += 1
                continue

            changed_fields = [f for f, v in defaults.items() if getattr(book, f) != v]
            if changed_fields:
                for field in changed_fields:
                    setattr(book, field, defaults[field])
                book.save()
                updated += 1
            else:
                unchanged += 1

        self.stdout.write(
            self.style.SUCCESS(f"Catalog loaded: {created} created, {updated} updated, {unchanged} unchanged.")
        )
