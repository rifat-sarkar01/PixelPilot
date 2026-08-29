"""Unit tests for the Ollama REST client using httpx MockTransport."""

import json

import httpx
import pytest

from pixelpilot.ollama.client import OllamaAPIError, OllamaClient, OllamaConnectionError


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _tags_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:14b", "size": 1024}]})


def test_ping_ok():
    client = OllamaClient(transport=_mock_transport(_tags_response))
    assert client.ping() is True


def test_ping_unreachable():
    def handler(request):
        raise httpx.ConnectError("boom")

    client = OllamaClient(transport=_mock_transport(handler))
    assert client.ping() is False


def test_list_models():
    client = OllamaClient(transport=_mock_transport(_tags_response))
    models = client.list_models()
    assert models[0]["name"] == "qwen2.5-coder:14b"


def test_show_model():
    def handler(request):
        return httpx.Response(200, json={"name": "qwen2.5-coder:14b", "parameter_size": "14B"})

    client = OllamaClient(transport=_mock_transport(handler))
    info = client.show_model("qwen2.5-coder:14b")
    assert info["parameter_size"] == "14B"


def test_chat_nonstream():
    def handler(request):
        assert "/api/chat" in str(request.url)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = OllamaClient(transport=_mock_transport(handler))
    resp = client.chat("m", [{"role": "user", "content": "hi"}], stream=False)
    assert resp["message"]["content"] == "ok"


def test_generate_stream_collected():
    payload = "\n".join(
        json.dumps({"response": chunk, "done": False})
        for chunk in ["hel", "lo ", "world"]
    ) + "\n" + json.dumps({"response": "", "done": True})

    def handler(request):
        return httpx.Response(200, content=payload.encode(), headers={"Content-Type": "application/x-ndjson"})

    from pixelpilot.ollama.streaming import collect_generate_stream

    client = OllamaClient(transport=_mock_transport(handler))
    chunks = client.generate("m", "prompt", stream=True)
    assert collect_generate_stream(chunks) == "hello world"


def test_chat_stream_collected():
    payload = "\n".join(
        json.dumps({"message": {"role": "assistant", "content": chunk}, "done": False})
        for chunk in ["a", "b", "c"]
    ) + "\n" + json.dumps({"done": True})

    def handler(request):
        return httpx.Response(200, content=payload.encode(), headers={"Content-Type": "application/x-ndjson"})

    from pixelpilot.ollama.streaming import collect_chat_stream

    client = OllamaClient(transport=_mock_transport(handler))
    chunks = client.chat("m", [{"role": "user", "content": "x"}], stream=True)
    assert collect_chat_stream(chunks) == "abc"


def test_embed():
    def handler(request):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    client = OllamaClient(transport=_mock_transport(handler))
    embeddings = client.embed("nomic-embed-text", ["hello"])
    assert embeddings == [[0.1, 0.2, 0.3]]


def test_api_error_raises():
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    client = OllamaClient(transport=_mock_transport(handler))
    with pytest.raises(OllamaAPIError) as exc_info:
        client.show_model("nope")
    assert exc_info.value.status_code == 404


def test_connection_error_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    client = OllamaClient(transport=_mock_transport(handler))
    with pytest.raises(OllamaConnectionError):
        client.list_models()


def test_think_false_passed_in_payload():
    """think=False must appear in the request body for hybrid-reasoning models."""
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = OllamaClient(transport=_mock_transport(handler))
    client.chat("m", [{"role": "user", "content": "hi"}], stream=False, think=False)
    assert captured["body"]["think"] is False


def test_think_true_passed_in_payload():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = OllamaClient(transport=_mock_transport(handler))
    client.chat("m", [{"role": "user", "content": "hi"}], stream=False, think=True)
    assert captured["body"]["think"] is True


def test_think_not_sent_when_omitted():
    """When think is not passed, it must not appear in the payload."""
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = OllamaClient(transport=_mock_transport(handler))
    client.chat("m", [{"role": "user", "content": "hi"}], stream=False)
    assert "think" not in captured["body"]
