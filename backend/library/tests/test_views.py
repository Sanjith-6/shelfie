import pytest
from django.test import Client

from library.models import LibraryEntry

pytestmark = pytest.mark.django_db


def test_delete_library_entry_removes_it():
    entry = LibraryEntry.objects.create(title="Dune", author="Frank Herbert", resolution="auto")

    response = Client().delete(f"/api/library/{entry.id}")

    assert response.status_code == 204
    assert not LibraryEntry.objects.filter(id=entry.id).exists()


def test_delete_nonexistent_entry_returns_404_not_500():
    response = Client().delete("/api/library/999999")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
