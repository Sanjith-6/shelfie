import time
import uuid

from django.conf import settings
from PIL import Image
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .detector import detect_books
from .matcher import match
from .models import LibraryEntry
from .serializers import LibraryEntrySerializer
from .vlm_reader import read_spines

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _box_to_bbox(box: tuple[int, int, int, int]) -> list[int]:
    """detector.py boxes are (x1, y1, x2, y2); the API contract's bbox is
    [x, y, w, h] - a shape decided before real detection existed. Converting
    here rather than changing the contract the frontend already builds
    against."""
    x1, y1, x2, y2 = box
    return [x1, y1, x2 - x1, y2 - y1]


def _flatten_candidates(candidates):
    return [
        {
            "catalog_id": c.entry.id,
            "title": c.entry.title,
            "author": c.entry.author,
            "score": c.score,
            "reasons": c.reasons,
        }
        for c in candidates
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
        image = image.convert("RGB")
    except Exception:
        return Response(
            {"error": "invalid_image", "message": "File is not a readable image."},
            status=400,
        )

    scan_id = uuid.uuid4()
    crops_dir = settings.MEDIA_ROOT / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    scan_start = time.perf_counter()
    warnings = []

    t0 = time.perf_counter()
    detection = detect_books(image)
    detect_ms = int((time.perf_counter() - t0) * 1000)
    warnings.extend(detection.warnings)

    if detection.error is not None:
        total_ms = int((time.perf_counter() - scan_start) * 1000)
        return Response(
            {
                "scan_id": str(scan_id),
                "timings_ms": {"detect": detect_ms, "vlm": 0, "match": 0, "total": total_ms},
                "detected_count": 0,
                "spines": [],
                "warnings": warnings + [f"detection failed: {detection.error}"],
            }
        )

    detections = detection.detections
    crops = [d.crop for d in detections]

    t0 = time.perf_counter()
    read_result = read_spines(crops)
    vlm_ms = int((time.perf_counter() - t0) * 1000)

    spines = []
    match_ms = 0
    for det, read in zip(detections, read_result.reads):
        spine_id = uuid.uuid4()
        det.crop.save(crops_dir / f"{spine_id}.jpg", format="JPEG", quality=85)

        base_spine = {
            "spine_id": str(spine_id),
            "bbox": _box_to_bbox(det.box),
            "crop_url": f"{settings.MEDIA_URL}crops/{spine_id}.jpg",
        }

        if read.error is not None:
            # A 4th status value, not one of MatchStatus's three. MatchStatus
            # is closed and deliberately has no FAILED member - this means the
            # VLM call itself failed for this spine, not "no catalog match".
            spines.append(
                {
                    **base_spine,
                    "raw_read": {"title": None, "author": None},
                    "status": "failed",
                    "candidates": [],
                    "error": read.error,
                }
            )
            continue

        if read.title is None:
            # VLM correctly declined rather than guessing - distinct from
            # "matcher found nothing" even though both surface as unmatched,
            # so the error field carries which one actually happened.
            spines.append(
                {
                    **base_spine,
                    "raw_read": {"title": None, "author": read.author},
                    "status": "unmatched",
                    "candidates": [],
                    "error": "vlm_could_not_read_spine",
                }
            )
            continue

        t_match = time.perf_counter()
        match_result = match(read.title, read.author or "")
        match_ms += int((time.perf_counter() - t_match) * 1000)

        spines.append(
            {
                **base_spine,
                "raw_read": {"title": read.title, "author": read.author},
                "status": match_result.status.value,
                "candidates": _flatten_candidates(match_result.candidates),
                "error": None,
            }
        )

    total_ms = int((time.perf_counter() - scan_start) * 1000)

    return Response(
        {
            "scan_id": str(scan_id),
            "timings_ms": {"detect": detect_ms, "vlm": vlm_ms, "match": match_ms, "total": total_ms},
            "detected_count": len(spines),
            "spines": spines,
            "warnings": warnings,
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
