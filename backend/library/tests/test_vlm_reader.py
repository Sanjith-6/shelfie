import httpx
import pytest
from PIL import Image

from library import vlm_reader
from library.vlm_reader import VlmMode, _repair_json, read_spines


def _make_image():
    return Image.new("RGB", (10, 10))


class _FakeUsage:
    def __init__(self, input_tokens=10, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeBlock(text)]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self.messages = _FakeMessages(response=response, exc=exc)


def test_repair_json_strips_code_fence():
    raw = '```json\n{"title": "Dune", "author": null}\n```'
    assert _repair_json(raw) == '{"title": "Dune", "author": null}'


def test_repair_json_extracts_outer_braces_from_prose():
    raw = 'Sure, here is the result: {"title": "Dune", "author": null} hope that helps!'
    assert _repair_json(raw) == '{"title": "Dune", "author": null}'


def test_batched_missing_index_fails_individually_not_whole_batch(monkeypatch):
    # Model only returned index 0 and 2, dropping index 1 - the response is
    # otherwise well-formed, so this must not be treated as malformed.
    response = _FakeResponse(
        '{"books": [{"index": 0, "title": "Dune", "author": "Herbert"}, '
        '{"index": 2, "title": "1984", "author": "Orwell"}]}'
    )
    monkeypatch.setattr(vlm_reader, "_make_client", lambda: _FakeClient(response=response))

    result = read_spines([_make_image(), _make_image(), _make_image()], mode=VlmMode.BATCHED)

    assert len(result.reads) == 3
    assert result.reads[0].title == "Dune" and result.reads[0].error is None
    assert result.reads[1].error == "vlm_missing_from_response"
    assert result.reads[2].title == "1984" and result.reads[2].error is None


def test_batched_null_title_passes_through_as_none(monkeypatch):
    response = _FakeResponse('{"books": [{"index": 0, "title": null, "author": null}]}')
    monkeypatch.setattr(vlm_reader, "_make_client", lambda: _FakeClient(response=response))

    result = read_spines([_make_image()], mode=VlmMode.BATCHED)

    assert result.reads[0].title is None
    assert result.reads[0].author is None
    assert result.reads[0].error is None


def test_batched_whole_call_failure_fails_each_spine_individually(monkeypatch):
    import anthropic

    timeout_error = anthropic.APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    monkeypatch.setattr(vlm_reader, "_make_client", lambda: _FakeClient(exc=timeout_error))

    result = read_spines([_make_image(), _make_image()], mode=VlmMode.BATCHED)

    assert len(result.reads) == 2
    assert all(r.error == "vlm_timeout" for r in result.reads)


def test_per_spine_one_failure_does_not_affect_others(monkeypatch):
    calls = {"n": 0}
    ok_response = _FakeResponse('{"title": "Dune", "author": "Herbert"}')

    import anthropic

    def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://example.test"))
        return ok_response

    fake_client = _FakeClient()
    fake_client.messages.create = fake_create
    monkeypatch.setattr(vlm_reader, "_make_client", lambda: fake_client)

    result = read_spines([_make_image(), _make_image(), _make_image()], mode=VlmMode.PER_SPINE)

    assert result.reads[0].title == "Dune" and result.reads[0].error is None
    assert result.reads[1].error == "vlm_timeout"
    assert result.reads[2].title == "Dune" and result.reads[2].error is None


def test_empty_crop_list_short_circuits_without_a_client(monkeypatch):
    def fail_if_called():
        raise AssertionError("_make_client should not be called for an empty crop list")

    monkeypatch.setattr(vlm_reader, "_make_client", fail_if_called)

    result = read_spines([])

    assert result.reads == []
