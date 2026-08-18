from rest_framework import serializers

from .models import LibraryEntry


class LibraryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LibraryEntry
        fields = [
            "id",
            "catalog_book",
            "title",
            "author",
            "raw_title",
            "raw_author",
            "confidence",
            "resolution",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
