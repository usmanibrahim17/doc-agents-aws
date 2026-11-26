import io
import json
import urllib.error

import pytest

from app.common import providers
from app.common.providers import BedrockProvider, FilePart, GeminiProvider
from app.common.schemas import CLASSIFICATION


@pytest.fixture(autouse=True)
def _no_aws_no_sleep(monkeypatch):
    monkeypatch.setattr(providers, "get_gemini_api_key", lambda name: "test-key")
    monkeypatch.setattr(providers.time, "sleep", lambda seconds: None)


def _reply(monkeypatch, *outcomes):
    """Each outcome is a response dict, or an HTTP status code to fail with."""
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(request.full_url, outcome, "x", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps(outcome).encode())

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_gemini_sends_file_and_schema_and_parses_json(monkeypatch):
    calls = _reply(
        monkeypatch,
        {
            "candidates": [{"content": {"parts": [{"text": '{"document_type": "invoice"}'}]}}],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 3,
                "thoughtsTokenCount": 2,
            },
        },
    )
    result = GeminiProvider("models/m", "/p").generate_json(
        "sys", "classify", CLASSIFICATION, FilePart(b"%PDF", "application/pdf")
    )
    assert result.data == {"document_type": "invoice"}
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    body = json.loads(calls[0].data)
    assert body["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "application/pdf"
    assert body["generationConfig"]["responseJsonSchema"] == CLASSIFICATION
    assert "test-key" not in calls[0].full_url


@pytest.mark.parametrize(
    ("statuses", "error"),
    [
        ((429, 429), providers.RateLimited),
        ((503, 503), providers.TransientError),
        ((400,), providers.ProviderError),
    ],
)
def test_gemini_http_errors(monkeypatch, statuses, error):
    calls = _reply(monkeypatch, *statuses)
    with pytest.raises(error) as caught:
        GeminiProvider("m", "/p").generate_json("s", "p", {})
    assert type(caught.value) is error  # Step Functions matches the exact class name
    assert len(calls) == len(statuses)
    assert "test-key" not in str(caught.value)


def test_gemini_rejects_non_json(monkeypatch):
    _reply(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "sorry"}]}}]})
    with pytest.raises(providers.ProviderError):
        GeminiProvider("m", "/p").generate_json("s", "p", {})


class StubBedrock:
    def __init__(self):
        self.request = None

    def converse(self, **request):
        self.request = request
        return {
            "output": {"message": {"content": [{"toolUse": {"input": {"ok": True}}}]}},
            "usage": {"inputTokens": 7, "outputTokens": 1},
        }


def test_bedrock_forces_tool_call():
    stub = StubBedrock()
    result = BedrockProvider("model", client=stub).generate_json(
        "s", "p", {"type": "object"}, FilePart(b"png", "image/png")
    )
    assert result.data == {"ok": True}
    assert stub.request["messages"][0]["content"][0]["image"]["format"] == "png"
    assert stub.request["toolConfig"]["toolChoice"] == {"tool": {"name": "answer"}}
