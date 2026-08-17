from dataclasses import dataclass

from PIL import Image
from ultralytics import YOLO

# Loaded once per process. yolov8n.pt is ~6MB, pretrained on COCO (which
# includes a "book" class) - no fine-tuning, CPU inference, exactly the
# "pretrained, off-the-shelf" local model the task calls for.
_MODEL: YOLO | None = None

# Low on purpose: COCO's "book" class was mostly trained on stacked/
# front-facing books, not thin vertical spines, so real shelf photos
# under-trigger at default confidence. We'd rather over-detect here and
# let the matcher/review step discard junk than miss real spines.
CONFIDENCE_THRESHOLD = 0.15
PADDING_RATIO = 0.03  # small margin so crops don't clip edge text


def _get_model() -> YOLO:
    global _MODEL
    if _MODEL is None:
        _MODEL = YOLO("yolov8n.pt")
    return _MODEL


@dataclass
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels
    confidence: float
    crop: Image.Image


def detect_books(image: Image.Image) -> list[Detection]:
    """Find book-shaped regions in a bookshelf photo. Returns an empty list
    (never raises) when nothing is detected - zero detections is a normal
    outcome the caller must handle, not an error."""
    model = _get_model()
    book_class_id = next(
        cls_id for cls_id, name in model.names.items() if name == "book"
    )

    results = model.predict(
        image, classes=[book_class_id], conf=CONFIDENCE_THRESHOLD, verbose=False
    )

    detections = []
    width, height = image.size
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            confidence = float(box.conf[0])

            pad_x = (x2 - x1) * PADDING_RATIO
            pad_y = (y2 - y1) * PADDING_RATIO
            x1 = max(0, int(x1 - pad_x))
            y1 = max(0, int(y1 - pad_y))
            x2 = min(width, int(x2 + pad_x))
            y2 = min(height, int(y2 + pad_y))

            crop = image.crop((x1, y1, x2, y2))
            detections.append(
                Detection(box=(x1, y1, x2, y2), confidence=confidence, crop=crop)
            )

    detections.sort(key=lambda d: d.confidence, reverse=True)
    return detections
