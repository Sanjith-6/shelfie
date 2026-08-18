import logging
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

logger = logging.getLogger(__name__)

# Loaded once per process. yolov8n.pt is ~6MB, pretrained on COCO - no
# training, no fine-tuning, CPU inference. First call on a fresh machine
# downloads the weights from Ultralytics' release assets (see the log line
# in _get_model and the README warning about it).
_MODEL: YOLO | None = None

# COCO-80's remapped class index for "book" (Ultralytics' coco.yaml order,
# not the raw COCO-91 category id) - hardcoded rather than looked up by
# name, per spec.
BOOK_CLASS_ID = 73

# Low on purpose: COCO's "book" class was mostly trained on stacked/
# front-facing books, not thin vertical spines, so real shelf photos
# under-trigger at default confidence. We'd rather over-detect here and
# let the aspect/size filter and the review step discard junk than miss
# real spines.
CONFIDENCE_THRESHOLD = 0.15
PADDING_RATIO = 0.03  # small margin so crops don't clip edge text

# Fewer usable YOLO boxes than this triggers the edge-density fallback.
FALLBACK_MIN_YOLO_BOXES = 2

# --- Aspect-ratio / size filtering, applied to both paths' output. ---
# Hand-set by reasoning about this task, not from labelled data - same
# caveat as matcher.py's thresholds. Deliberately orientation-agnostic:
# test photos include books stacked flat as well as upright, so a "tall
# and narrow" filter would drop real books lying on their side.
MAX_ASPECT_RATIO = 12.0  # max(w,h)/min(w,h) - catches slivers/shadows in either orientation
MIN_BOX_DIMENSION_FRACTION = 0.015  # of the image's matching dimension
MAX_BOX_DIMENSION_FRACTION = 0.70  # a box this big is probably "the whole shelf", not one book

# --- Fallback strip-slicing tuning. Also hand-set. ---
SMOOTH_WINDOW_FRACTION = 0.01  # moving-average window, as a fraction of image width
MIN_STRIP_WIDTH_FRACTION = 0.02  # minimum spacing between detected boundaries
PEAK_HEIGHT_FRACTION = 0.3  # a boundary candidate must clear this fraction of the signal's range


@dataclass
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels
    confidence: float | None  # None for fallback detections - there's no real score to report
    crop: Image.Image


@dataclass
class DetectionResult:
    detections: list[Detection]
    path_used: str  # "yolo", "fallback", or "none" (whole-detector failure)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None  # None on success; a specific code on whole-detector failure


def _get_model() -> YOLO:
    global _MODEL
    if _MODEL is None:
        logger.info(
            "Loading YOLOv8n weights - first run on this machine downloads "
            "~6MB from Ultralytics' release assets."
        )
        _MODEL = YOLO("yolov8n.pt")
        logger.info("YOLOv8n loaded.")
    return _MODEL


def _filter_box(box: tuple[int, int, int, int], image_width: int, image_height: int) -> str | None:
    """Returns a drop reason if the box should be rejected, None if it
    passes."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return "degenerate (zero or negative size)"
    if w < image_width * MIN_BOX_DIMENSION_FRACTION or h < image_height * MIN_BOX_DIMENSION_FRACTION:
        return "too small"
    if w > image_width * MAX_BOX_DIMENSION_FRACTION or h > image_height * MAX_BOX_DIMENSION_FRACTION:
        return "too large"
    if max(w, h) / min(w, h) > MAX_ASPECT_RATIO:
        return "too elongated"
    return None


def _crop_with_padding(
    image: Image.Image, box: tuple[float, float, float, float]
) -> tuple[tuple[int, int, int, int], Image.Image]:
    x1, y1, x2, y2 = box
    width, height = image.size
    pad_x = (x2 - x1) * PADDING_RATIO
    pad_y = (y2 - y1) * PADDING_RATIO
    x1 = max(0, int(x1 - pad_x))
    y1 = max(0, int(y1 - pad_y))
    x2 = min(width, int(x2 + pad_x))
    y2 = min(height, int(y2 + pad_y))
    padded_box = (x1, y1, x2, y2)
    return padded_box, image.crop(padded_box)


def _run_yolo(image: Image.Image, model: YOLO) -> list[Detection]:
    results = model.predict(image, classes=[BOOK_CLASS_ID], conf=CONFIDENCE_THRESHOLD, verbose=False)

    detections = []
    for result in results:
        for box in result.boxes:
            try:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                confidence = float(box.conf[0])
                padded_box, crop = _crop_with_padding(image, (x1, y1, x2, y2))
                detections.append(Detection(box=padded_box, confidence=confidence, crop=crop))
            except Exception as exc:
                # One bad box (e.g. a degenerate crop region) must not cost
                # the rest of the boxes YOLO found.
                logger.warning("Dropped one YOLO box during crop: %s", exc)
    return detections


def _find_peaks(signal: np.ndarray, min_spacing: int, height_fraction: float) -> list[int]:
    """Hand-rolled local-maxima finder: a point is a peak if it's the max
    within +/- min_spacing of itself and clears a height floor relative to
    the signal's own range. No scipy - this is the only place that would
    want it, not worth the dependency for one small piece of a fallback
    path."""
    if len(signal) == 0 or signal.max() == signal.min():
        return []
    threshold = signal.min() + (signal.max() - signal.min()) * height_fraction
    peaks: list[int] = []
    for i in range(len(signal)):
        window = signal[max(0, i - min_spacing) : min(len(signal), i + min_spacing + 1)]
        if signal[i] >= threshold and signal[i] == window.max():
            if not peaks or i - peaks[-1] >= min_spacing:
                peaks.append(i)
    return peaks


def _run_fallback(image: Image.Image) -> list[Detection]:
    """Slices the shelf into vertical strips by edge density. YOLO is weak
    on tightly-packed vertical spines, so when it under-detects, this is
    the backstop. Sobel-X specifically, not Canny - it's the horizontal-
    gradient kernel, so it responds to vertical edges, which is the
    direction spine boundaries actually run in."""
    width, height = image.size
    gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    sobel_x = cv2.Sobel(gray, cv2.CV_64F, dx=1, dy=0, ksize=3)
    column_energy = np.abs(sobel_x).sum(axis=0)  # 1D, length = width

    window_size = max(1, int(width * SMOOTH_WINDOW_FRACTION))
    kernel = np.ones(window_size) / window_size
    smoothed = np.convolve(column_energy, kernel, mode="same")

    min_spacing = max(1, int(width * MIN_STRIP_WIDTH_FRACTION))
    peaks = _find_peaks(smoothed, min_spacing, PEAK_HEIGHT_FRACTION)
    boundaries = sorted({0, *peaks, width})

    detections = []
    for x1, x2 in zip(boundaries, boundaries[1:]):
        try:
            box = (x1, 0, x2, height)
            crop = image.crop(box)
            detections.append(Detection(box=box, confidence=None, crop=crop))
        except Exception as exc:
            logger.warning("Dropped one fallback strip during crop: %s", exc)
    return detections


def _filter_and_log(detections: list[Detection], width: int, height: int, pass_name: str) -> list[Detection]:
    kept = []
    dropped_reasons: dict[str, int] = {}
    for d in detections:
        reason = _filter_box(d.box, width, height)
        if reason is None:
            kept.append(d)
        else:
            dropped_reasons[reason] = dropped_reasons.get(reason, 0) + 1

    if dropped_reasons:
        logger.info(
            "%s pass: dropped %d of %d boxes (%s)",
            pass_name,
            sum(dropped_reasons.values()),
            len(detections),
            dropped_reasons,
        )
    return kept


def detect_books(image: Image.Image) -> DetectionResult:
    """Find book-shaped regions in a bookshelf photo. Never raises - a
    whole-detector failure (model won't load, inference throws) comes back
    as an empty result with an error code, not an exception; a single bad
    box within an otherwise-good detection is dropped and logged, not
    fatal to the rest of the scan. Side-effect free: takes an image,
    returns in-memory crops, knows nothing about scan IDs or the
    filesystem - that's the caller's job."""
    width, height = image.size

    try:
        model = _get_model()
    except Exception as exc:
        logger.error("Failed to load YOLO weights: %s", exc)
        return DetectionResult(detections=[], path_used="none", error="detector_load_failed")

    try:
        yolo_detections = _run_yolo(image, model)
    except Exception as exc:
        logger.error("YOLO inference failed: %s", exc)
        return DetectionResult(detections=[], path_used="none", error="detector_inference_failed")

    kept = _filter_and_log(yolo_detections, width, height, "YOLO")

    if len(kept) >= FALLBACK_MIN_YOLO_BOXES:
        return DetectionResult(
            detections=kept,
            path_used="yolo",
            warnings=["detected via local YOLO model"],
        )

    # Fallback: YOLO under-detected (tightly packed spines are its known
    # weak spot) - replace its output with edge-density strip slicing.
    try:
        fallback_detections = _run_fallback(image)
    except Exception as exc:
        logger.error("Fallback edge-density detection also failed: %s", exc)
        return DetectionResult(
            detections=[],
            path_used="none",
            error="detector_fallback_failed",
            warnings=[f"YOLO found only {len(kept)} usable box(es), and the fallback failed too"],
        )

    kept_fallback = _filter_and_log(fallback_detections, width, height, "Fallback")

    return DetectionResult(
        detections=kept_fallback,
        path_used="fallback",
        warnings=[f"used edge-density fallback: YOLO found only {len(kept)} usable box(es)"],
    )
