import base64
import io
import json
from dataclasses import dataclass

import anthropic
from django.conf import settings
from PIL import Image

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
REQUEST_TIMEOUT = 30.0

# One VLM call per bookshelf photo, not one per spine: every crop from a
# photo goes into a single request as separate image blocks. Cost and
# latency then scale with photos taken, not books on the shelf, and we pay
# the fixed per-request prompt overhead once instead of N times.
PROMPT = (
    "Each image below is a cropped photo of a single book spine from a "
    "bookshelf, numbered in order starting at 0. For each image, read the "
    "title and author printed on the spine. If the spine is blurry, cut "
    "off, or you cannot confidently read it, set readable to false and "
    "give your best partial guess for title/author (empty string if you "
    "have nothing at all). Return exactly one entry per image, in order."
)

# Forces a schema-valid JSON response rather than relying on prompt
# instructions alone - the model can still refuse or hit stop_reason
# "max_tokens", but it can't return free-text that fails to parse.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "readable": {"type": "boolean"},
                },
                "required": ["index", "title", "author", "readable"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["books"],
    "additionalProperties": False,
}


@dataclass
class SpineRead:
    index: int
    title: str
    author: str
    readable: bool


@dataclass
class ReadResult:
    reads: list[SpineRead]
    # None on success. Set to a short machine-readable code on failure so
    # the view can surface a specific, honest message instead of a generic
    # 500 - a timeout, a refusal, and a malformed response are all
    # different situations for the user to see.
    error: str | None = None


def _encode_jpeg(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def read_spines(crops: list[Image.Image]) -> ReadResult:
    if not crops:
        return ReadResult(reads=[])

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    )

    content = []
    for i, crop in enumerate(crops):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _encode_jpeg(crop),
                },
            }
        )
    content.append({"type": "text", "text": PROMPT})

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APITimeoutError:
        return ReadResult(reads=[], error="vlm_timeout")
    except anthropic.RateLimitError:
        return ReadResult(reads=[], error="vlm_rate_limited")
    except anthropic.APIConnectionError:
        return ReadResult(reads=[], error="vlm_connection_error")
    except anthropic.APIStatusError as exc:
        return ReadResult(reads=[], error=f"vlm_api_error_{exc.status_code}")

    if response.stop_reason == "refusal":
        return ReadResult(reads=[], error="vlm_refusal")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return ReadResult(reads=[], error="vlm_empty_response")

    try:
        data = json.loads(text)
        reads = [
            SpineRead(
                index=entry["index"],
                title=entry["title"],
                author=entry["author"],
                readable=entry["readable"],
            )
            for entry in data["books"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return ReadResult(reads=[], error="vlm_malformed_response")

    return ReadResult(reads=reads)
