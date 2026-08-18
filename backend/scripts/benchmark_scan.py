"""Benchmarks the real detect -> VLM -> match pipeline against the 7 fixture
photos. Calls the same functions views.py wires together directly, rather
than the HTTP view - needed to capture ReadResult's token counts for cost
math (the view discards them) and to run both VLM modes per photo without
touching the VLM_MODE constant.

Makes real, billed Anthropic API calls. Requires a real ANTHROPIC_API_KEY in
backend/.env.

Usage (from the repo root):
    backend/.venv/Scripts/python.exe backend/scripts/benchmark_scan.py --mode batched
    backend/.venv/Scripts/python.exe backend/scripts/benchmark_scan.py --mode per_spine
    backend/.venv/Scripts/python.exe backend/scripts/benchmark_scan.py --mode both
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shelfie_api.settings")
import django  # noqa: E402

django.setup()

import time  # noqa: E402

from PIL import Image  # noqa: E402

from library.detector import detect_books  # noqa: E402
from library.matcher import match  # noqa: E402
from library.vlm_reader import VlmMode, read_spines  # noqa: E402

# Published per-million-token pricing for MODEL in vlm_reader.py
# ("claude-sonnet-5"). Left unset on purpose - filled in with a verified
# number from Anthropic's pricing page right before the benchmark runs,
# rather than guessed here. Token counts are printed regardless; cost math
# is skipped (not estimated) until these are real.
INPUT_COST_PER_MTOK: float | None = None
OUTPUT_COST_PER_MTOK: float | None = None

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "photos"
PHOTO_NAMES = [f"shelf_{i}.jpg" for i in range(1, 8)]


def run_one(photo_path: Path, mode: VlmMode) -> dict:
    image = Image.open(photo_path).convert("RGB")

    t0 = time.perf_counter()
    detection = detect_books(image)
    detect_ms = (time.perf_counter() - t0) * 1000

    if detection.error is not None:
        return {"photo": photo_path.name, "mode": mode.value, "error": detection.error}

    crops = [d.crop for d in detection.detections]

    t0 = time.perf_counter()
    read_result = read_spines(crops, mode=mode)
    vlm_ms = (time.perf_counter() - t0) * 1000

    match_ms = 0.0
    statuses: list[str] = []
    for read in read_result.reads:
        if read.error is not None:
            statuses.append("failed")
            continue
        if read.title is None:
            statuses.append("unmatched")
            continue
        t0 = time.perf_counter()
        result = match(read.title, read.author or "")
        match_ms += (time.perf_counter() - t0) * 1000
        statuses.append(result.status.value)

    total_ms = detect_ms + vlm_ms + match_ms

    cost_usd = None
    if INPUT_COST_PER_MTOK is not None and OUTPUT_COST_PER_MTOK is not None:
        cost_usd = round(
            read_result.input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
            + read_result.output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK,
            4,
        )

    return {
        "photo": photo_path.name,
        "mode": mode.value,
        "detected_count": len(detection.detections),
        "detect_ms": round(detect_ms),
        "vlm_ms": round(vlm_ms),
        "match_ms": round(match_ms),
        "total_ms": round(total_ms),
        "status_counts": {s: statuses.count(s) for s in set(statuses)},
        "input_tokens": read_result.input_tokens,
        "output_tokens": read_result.output_tokens,
        "cost_usd": cost_usd,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["batched", "per_spine", "both"], default="batched")
    args = parser.parse_args()

    modes = {
        "batched": [VlmMode.BATCHED],
        "per_spine": [VlmMode.PER_SPINE],
        "both": [VlmMode.BATCHED, VlmMode.PER_SPINE],
    }[args.mode]

    rows = []
    for name in PHOTO_NAMES:
        for mode in modes:
            print(f"Running {name} in {mode.value} mode...", file=sys.stderr)
            row = run_one(PHOTOS_DIR / name, mode)
            rows.append(row)
            print(row)

    print("\n--- summary ---")
    for row in rows:
        if "error" in row:
            print(f"{row['photo']:12s} {row['mode']:10s} ERROR: {row['error']}")
            continue
        print(
            f"{row['photo']:12s} {row['mode']:10s} "
            f"spines={row['detected_count']:3d} "
            f"detect={row['detect_ms']:5d}ms vlm={row['vlm_ms']:6d}ms "
            f"match={row['match_ms']:4d}ms total={row['total_ms']:6d}ms "
            f"tokens_in={row['input_tokens']:5d} tokens_out={row['output_tokens']:4d} "
            f"cost=${row['cost_usd']} "
            f"statuses={row['status_counts']}"
        )


if __name__ == "__main__":
    main()
