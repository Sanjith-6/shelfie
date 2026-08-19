import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum

import anthropic
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 1  # one retry, then that call fails - not the SDK's default of 2

# Anthropic rejects many-image requests containing any image over 2000px on
# its longest edge. Found this in production-shaped testing, not the docs -
# real fallback-path crops (full image height, easily 4000px+) and some
# dense-shelf YOLO crops both cross it. 1800px leaves margin below the hard
# limit and spine text is still legible at that size.
MAX_CROP_DIMENSION = 1800

# Crops per batched API call. Also found empirically: sending 35-46 crops in
# one request is slow enough to blow the 30s timeout even when every crop is
# under the size limit. Chunking keeps each request's payload and processing
# time bounded, at the cost of paying the per-request prompt overhead once
# per chunk instead of once per photo.
BATCH_CHUNK_SIZE = 10


class VlmMode(str, Enum):
    BATCHED = "batched"  # every crop from a photo in one call
    PER_SPINE = "per_spine"  # one call per crop


# Batched is the default: one photo's worth of crops in a single request, so
# cost and latency scale with photos taken, not books on the shelf, and we
# pay the fixed per-request prompt overhead once instead of N times. Callers
# (the benchmark script in particular) can override per call to compare both.
VLM_MODE = VlmMode.BATCHED

# Explicitly permits null - a spine the model genuinely can't read should
# come back null, not a hallucinated guess dressed up as a real title. Say
# it this bluntly because the obvious alternative (a "best guess" field) is
# exactly what makes VLM reads untrustworthy for a catalog match downstream.
PROMPT_BATCHED = (
    "Each image below is a cropped photo of a single book spine from a "
    "bookshelf, numbered in order starting at 0. For each image, read the "
    "title and author printed on the spine. If the spine is blurry, cut "
    "off, at an angle you can't read, or you are not confident, set title "
    "and/or author to null. Do not guess - a null is correct behavior, a "
    "guessed title is not. Return exactly one entry per image, in order."
)

PROMPT_SINGLE = (
    "This image is a cropped photo of a single book spine from a "
    "bookshelf. Read the title and author printed on the spine. If the "
    "spine is blurry, cut off, at an angle you can't read, or you are not "
    "confident, set title and/or author to null. Do not guess - a null is "
    "correct behavior, a guessed title is not."
)

# Forces a schema-valid JSON response rather than relying on prompt
# instructions alone - the model can still refuse or hit stop_reason
# "max_tokens", but it can't return free-text that fails to parse.
RESPONSE_SCHEMA_BATCHED = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                },
                "required": ["index", "title", "author"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["books"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA_SINGLE = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"]},
        "author": {"type": ["string", "null"]},
    },
    "required": ["title", "author"],
    "additionalProperties": False,
}


@dataclass
class SpineRead:
    index: int
    title: str | None
    author: str | None
    # None on success. Set to a short machine-readable code if this specific
    # spine's read failed - a timeout, a refusal, and a response that never
    # mentioned this index are different situations for the caller to see,
    # and one bad spine must not cost the rest of the photo's reads.
    error: str | None = None


@dataclass
class ReadResult:
    reads: list[SpineRead]  # always one entry per crop passed in, in order
    input_tokens: int = 0
    output_tokens: int = 0


def _encode_jpeg(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def _resize_if_needed(image: Image.Image, index: int) -> Image.Image:
    longest_edge = max(image.size)
    if longest_edge <= MAX_CROP_DIMENSION:
        return image
    scale = MAX_CROP_DIMENSION / longest_edge
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    logger.info("Resizing crop %d: %s -> %s (exceeded %dpx)", index, image.size, new_size, MAX_CROP_DIMENSION)
    return image.resize(new_size, Image.LANCZOS)


def _repair_json(text: str) -> str:
    """Best-effort cleanup before giving up on a malformed response: models
    occasionally wrap JSON in a markdown code fence despite a schema-forced
    response, or trail whitespace/prose outside the braces."""
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )


def _call_error_code(exc: Exception) -> str:
    if isinstance(exc, anthropic.APITimeoutError):
        return "vlm_timeout"
    if isinstance(exc, anthropic.RateLimitError):
        return "vlm_rate_limited"
    if isinstance(exc, anthropic.APIConnectionError):
        return "vlm_connection_error"
    if isinstance(exc, anthropic.APIStatusError):
        return f"vlm_api_error_{exc.status_code}"
    return "vlm_unknown_error"


def _log_usage(mode: VlmMode, num_images: int, usage) -> None:
    logger.info(
        "VLM call (%s, %d image(s)): input_tokens=%d output_tokens=%d",
        mode.value,
        num_images,
        usage.input_tokens,
        usage.output_tokens,
    )


def _read_batched_chunk(client: anthropic.Anthropic, crops: list[Image.Image]) -> ReadResult:
    """One API call for one chunk of crops. Indices in the returned reads
    are local to this chunk (0..len(crops)-1) - the caller remaps them to
    the photo's real spine indices."""
    content = []
    for i, crop in enumerate(crops):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_jpeg(crop)},
            }
        )
    content.append({"type": "text", "text": PROMPT_BATCHED})

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA_BATCHED}},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        error = _call_error_code(exc)
        logger.error("Batched VLM call failed for %d crop(s): %s", len(crops), error)
        return ReadResult(reads=[SpineRead(index=i, title=None, author=None, error=error) for i in range(len(crops))])

    _log_usage(VlmMode.BATCHED, len(crops), response.usage)

    if response.stop_reason == "refusal":
        return ReadResult(
            reads=[SpineRead(index=i, title=None, author=None, error="vlm_refusal") for i in range(len(crops))],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return ReadResult(
            reads=[SpineRead(index=i, title=None, author=None, error="vlm_empty_response") for i in range(len(crops))],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    entries_by_index: dict[int, dict] = {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(_repair_json(text))
        except json.JSONDecodeError:
            data = None

    if data is not None:
        try:
            for entry in data["books"]:
                entries_by_index[entry["index"]] = entry
        except (KeyError, TypeError):
            entries_by_index = {}

    reads = []
    for i in range(len(crops)):
        entry = entries_by_index.get(i)
        if entry is None:
            reads.append(SpineRead(index=i, title=None, author=None, error="vlm_missing_from_response"))
            continue
        try:
            reads.append(SpineRead(index=i, title=entry["title"], author=entry["author"]))
        except (KeyError, TypeError):
            reads.append(SpineRead(index=i, title=None, author=None, error="vlm_malformed_response"))

    return ReadResult(reads=reads, input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)


def _read_batched_all(client: anthropic.Anthropic, crops: list[Image.Image]) -> ReadResult:
    """Splits crops into BATCH_CHUNK_SIZE-sized calls. Each chunk is its own
    independent API call - one chunk timing out or erroring must not affect
    any other chunk's results, same isolation guarantee as per-spine mode,
    just at chunk granularity instead of single-crop granularity."""
    reads: list[SpineRead] = []
    total_input, total_output = 0, 0
    for chunk_start in range(0, len(crops), BATCH_CHUNK_SIZE):
        chunk = crops[chunk_start : chunk_start + BATCH_CHUNK_SIZE]
        chunk_result = _read_batched_chunk(client, chunk)
        for r in chunk_result.reads:
            reads.append(SpineRead(index=chunk_start + r.index, title=r.title, author=r.author, error=r.error))
        total_input += chunk_result.input_tokens
        total_output += chunk_result.output_tokens
    return ReadResult(reads=reads, input_tokens=total_input, output_tokens=total_output)


def _read_single(client: anthropic.Anthropic, crop: Image.Image, index: int) -> tuple[SpineRead, int, int]:
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_jpeg(crop)},
        },
        {"type": "text", "text": PROMPT_SINGLE},
    ]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA_SINGLE}},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        error = _call_error_code(exc)
        logger.error("Per-spine VLM call failed for index %d: %s", index, error)
        return SpineRead(index=index, title=None, author=None, error=error), 0, 0

    _log_usage(VlmMode.PER_SPINE, 1, response.usage)
    tokens = (response.usage.input_tokens, response.usage.output_tokens)

    if response.stop_reason == "refusal":
        return SpineRead(index=index, title=None, author=None, error="vlm_refusal"), *tokens

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return SpineRead(index=index, title=None, author=None, error="vlm_empty_response"), *tokens

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(_repair_json(text))
        except json.JSONDecodeError:
            return SpineRead(index=index, title=None, author=None, error="vlm_malformed_response"), *tokens

    try:
        return SpineRead(index=index, title=data["title"], author=data["author"]), *tokens
    except (KeyError, TypeError):
        return SpineRead(index=index, title=None, author=None, error="vlm_malformed_response"), *tokens


def read_spines(crops: list[Image.Image], mode: VlmMode = VLM_MODE) -> ReadResult:
    if not crops:
        return ReadResult(reads=[])

    crops = [_resize_if_needed(crop, i) for i, crop in enumerate(crops)]
    client = _make_client()

    if mode == VlmMode.BATCHED:
        return _read_batched_all(client, crops)

    reads = []
    total_input, total_output = 0, 0
    for i, crop in enumerate(crops):
        read, input_tokens, output_tokens = _read_single(client, crop, i)
        reads.append(read)
        total_input += input_tokens
        total_output += output_tokens
    return ReadResult(reads=reads, input_tokens=total_input, output_tokens=total_output)
