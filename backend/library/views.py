import uuid

from django.conf import settings
from PIL import Image
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import LibraryEntry
from .serializers import LibraryEntrySerializer

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Hardcoded until detection/VLM/matching are wired in (later sessions).
# One spine per status this endpoint can return, so the frontend has a real
# example of each to build against instead of guessing at the shape.
STUB_SPINES = [
    {
        "raw_read": {"title": "1984", "author": "George Orwell"},
        "status": "auto",
        "candidates": [
            {
                "catalog_id": 1003,
                "title": "1984",
                "author": "George Orwell",
                "score": 0.97,
                "reasons": ["exact title match", "exact author match"],
            }
        ],
    },
    {
        "raw_read": {"title": "The Alchemist", "author": "Paulo Coelho"},
        "status": "review",
        "candidates": [
            {
                "catalog_id": 1005,
                "title": "The Alchemist",
                "author": "Paulo Coelho",
                "score": 0.82,
                "reasons": ["title match", "tied with another catalog edition"],
            },
            {
                "catalog_id": 1006,
                "title": "The Alchemist",
                "author": "Paulo Coelho",
                "score": 0.82,
                "reasons": ["title match", "tied with another catalog edition"],
            },
        ],
    },
    {
        "raw_read": {"title": "Some Illegible Spine", "author": None},
        "status": "unmatched",
        "candidates": [],
    },
]


@api_view(["POST"])
def scan(request):
    uploaded_file = request.FILES.get("image")
    if uploaded_file is None:
        return Response(
            {"error": "missing_image", "message": "No 'image' field in the request."},
            status=400,
        )

    if uploaded_file.size > MAX_UPLOAD_BYTES:
        return Response(
            {"error": "file_too_large", "message": "Image exceeds the 10MB limit."},
            status=400,
        )

    try:
        image = Image.open(uploaded_file)
        image.load()  # forces a full decode, catching truncated/invalid files
    except Exception:
        return Response(
            {"error": "invalid_image", "message": "File is not a readable image."},
            status=400,
        )

    scan_id = uuid.uuid4()
    crops_dir = settings.MEDIA_ROOT / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    # Real spine detection doesn't exist yet, so we fake plausible bounding
    # boxes by slicing the photo into vertical thirds - close enough to a
    # bookshelf's actual layout that the crops look sane, and it proves the
    # crop_url round trip end to end.
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    third_width = width // 3

    spines = []
    for i, stub in enumerate(STUB_SPINES):
        spine_id = uuid.uuid4()
        x1 = i * third_width
        x2 = width if i == len(STUB_SPINES) - 1 else (i + 1) * third_width
        bbox = [x1, 0, x2 - x1, height]

        crop = rgb_image.crop((x1, 0, x2, height))
        crop.save(crops_dir / f"{spine_id}.jpg", format="JPEG", quality=85)

        spines.append(
            {
                "spine_id": str(spine_id),
                "bbox": bbox,
                "crop_url": f"{settings.MEDIA_URL}crops/{spine_id}.jpg",
                "raw_read": stub["raw_read"],
                "status": stub["status"],
                "candidates": stub["candidates"],
                "error": None,
            }
        )

    return Response(
        {
            "scan_id": str(scan_id),
            "timings_ms": {"detect": 0, "vlm": 0, "match": 0, "total": 0},
            "detected_count": len(spines),
            "spines": spines,
            "warnings": [],
        }
    )


@api_view(["GET", "POST"])
def library(request):
    if request.method == "GET":
        entries = LibraryEntry.objects.all()
        return Response(LibraryEntrySerializer(entries, many=True).data)

    serializer = LibraryEntrySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=201)
