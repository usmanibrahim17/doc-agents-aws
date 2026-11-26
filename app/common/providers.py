"""AI provider: one interface, "documents + instructions in, schema-shaped JSON out".

AI_PROVIDER=gemini  -> Google Gemini over HTTPS (standard-library urllib, no Google SDK)
AI_PROVIDER=bedrock -> Amazon Bedrock Converse, using a forced tool call for the JSON shape

Unlike project 1, throttling is not slept through here: a 429 is retried once and then raised as
`RateLimited`, so Step Functions can back off without paying for a Lambda that is only waiting.
"""

import base64
import json
import random
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

from app.common.config import env

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_ATTEMPTS = 2
REQUEST_TIMEOUT_SECONDS = 60
TEMPERATURE = 0.0  # extraction and classification should be repeatable

# Upload types the pipeline accepts -> Bedrock "format" names.
MIME_TYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg"}


# Step Functions matches Retry/Catch on the exception class name: do not rename these casually.
class ProviderError(RuntimeError):
    """A provider call failed. Messages never contain keys, headers or response bodies."""


class RateLimited(ProviderError):
    """Rate limit or quota (HTTP 429). Retry later."""


class TransientError(ProviderError):
    """5xx or network problem. Retry later."""


@dataclass
class FilePart:
    data: bytes
    mime_type: str


@dataclass
class JsonResult:
    data: dict
    input_tokens: int
    output_tokens: int
    model: str


class Provider(ABC):
    @abstractmethod
    def generate_json(
        self,
        system: str,
        prompt: str,
        schema: dict,
        file: FilePart | None = None,
        max_tokens: int = 4096,
    ) -> JsonResult:
        """Run the model on the prompt (and optional document) and return JSON matching schema."""


# --- Gemini ---------------------------------------------------------------------------------


@lru_cache
def get_gemini_api_key(param_name: str) -> str:
    """Read the API key from SSM once per Lambda container; later calls hit the cache."""
    import boto3

    response = boto3.client("ssm").get_parameter(Name=param_name, WithDecryption=True)
    return response["Parameter"]["Value"]


def _post_json(url: str, payload: dict, api_key: str) -> dict:
    """POST JSON to Gemini. The key travels in a header (never the URL) so it cannot leak."""
    data = json.dumps(payload).encode()
    status: int | None = None
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"content-type": "application/json", "x-goog-api-key": api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status != 429 and status < 500:
                raise ProviderError(f"Gemini request failed with HTTP {status}") from None
        except (urllib.error.URLError, TimeoutError):
            status = None

        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(random.uniform(1.0, 3.0))

    if status == 429:
        raise RateLimited("Gemini rate limit or quota exceeded (HTTP 429)")
    detail = f"HTTP {status}" if status else "network error"
    raise TransientError(f"Gemini request failed ({detail})")


class GeminiProvider(Provider):
    def __init__(self, model: str, key_param: str):
        self.model, self.key_param = model.removeprefix("models/"), key_param

    def generate_json(self, system, prompt, schema, file=None, max_tokens=4096):
        parts: list[dict] = []
        if file is not None:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": file.mime_type,
                        "data": base64.b64encode(file.data).decode(),
                    }
                }
            )
        parts.append({"text": prompt})
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": TEMPERATURE,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent"
        result = _post_json(url, payload, get_gemini_api_key(self.key_param))

        candidates = result.get("candidates") or []
        content = (candidates[0].get("content") or {}) if candidates else {}
        # Skip "thought" parts (a thinking model's reasoning).
        text = "".join(
            p.get("text", "") for p in content.get("parts", []) if not p.get("thought")
        ).strip()
        data = _parse_object(text)

        usage = result.get("usageMetadata") or {}
        # Thinking tokens are billed as output, so count them there.
        output = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        return JsonResult(data, usage.get("promptTokenCount", 0), output, self.model)


def _parse_object(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ProviderError("model did not return valid JSON") from None
    if not isinstance(data, dict):
        raise ProviderError("model did not return a JSON object")
    return data


# --- Bedrock --------------------------------------------------------------------------------


class BedrockProvider(Provider):
    def __init__(self, model_id: str, client=None):
        self.model_id = model_id
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime")
        return self._client

    def generate_json(self, system, prompt, schema, file=None, max_tokens=4096):
        content: list[dict] = []
        if file is not None:
            fmt = MIME_TYPES[file.mime_type]
            if fmt == "pdf":
                content.append(
                    {"document": {"format": fmt, "name": "upload", "source": {"bytes": file.data}}}
                )
            else:
                content.append({"image": {"format": fmt, "source": {"bytes": file.data}}})
        content.append({"text": prompt})
        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": content}],
                inferenceConfig={"temperature": TEMPERATURE, "maxTokens": max_tokens},
                toolConfig={
                    "tools": [{"toolSpec": {"name": "answer", "inputSchema": {"json": schema}}}],
                    "toolChoice": {"tool": {"name": "answer"}},
                },
            )
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            if code == "ThrottlingException":
                raise RateLimited("Bedrock throttled the request") from None
            raise ProviderError(f"Bedrock request failed ({code})") from None

        blocks = response["output"]["message"]["content"]
        data = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
        if not isinstance(data, dict):
            raise ProviderError("model did not return the expected tool call")
        usage = response.get("usage", {})
        return JsonResult(
            data, usage.get("inputTokens", 0), usage.get("outputTokens", 0), self.model_id
        )


# --- Factory --------------------------------------------------------------------------------


def get_provider() -> Provider:
    name = env("AI_PROVIDER", "gemini")
    if name == "gemini":
        return GeminiProvider(env("GEMINI_GENERATION_MODEL"), env("GEMINI_API_KEY_PARAM"))
    if name == "bedrock":
        return BedrockProvider(env("GENERATION_MODEL_ID"))
    raise RuntimeError(f"unknown AI_PROVIDER {name!r}")
