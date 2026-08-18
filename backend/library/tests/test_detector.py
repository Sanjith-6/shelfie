from PIL import Image

from library.detector import _dedup_by_iou, Detection


def _make_detection(box, confidence):
    # 1x1 placeholder - dedup only looks at .box and .confidence.
    return Detection(box=box, confidence=confidence, crop=Image.new("RGB", (1, 1)))


def test_heavily_overlapping_boxes_collapse_to_one():
    a = _make_detection((100, 100, 300, 400), confidence=0.8)
    b = _make_detection((110, 100, 310, 400), confidence=0.5)  # same region, shifted 10px

    result = _dedup_by_iou([a, b], iou_threshold=0.5)

    assert len(result) == 1
    assert result[0].confidence == 0.8  # higher-confidence box wins


def test_distinct_boxes_are_not_merged():
    a = _make_detection((0, 0, 100, 400), confidence=0.8)
    b = _make_detection((200, 0, 300, 400), confidence=0.5)  # no overlap at all

    result = _dedup_by_iou([a, b], iou_threshold=0.5)

    assert len(result) == 2
