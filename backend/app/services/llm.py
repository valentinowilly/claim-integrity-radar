"""One client for the language model behind document reading, note reading and document questions.

The model is served behind an OpenAI-compatible chat-completions endpoint, so the same code talks to:

* production: vLLM on the organisation's own GPU server (data never leaves it), e.g.
  ``CIR_LLM_BASE_URL=http://llm.internal:8000/v1`` and ``CIR_LLM_MODEL=google/gemma-4-31b-it``;
* development and demos with synthetic data: the same open model through the Gemini API's OpenAI-compatible
  endpoint (``CIR_LLM_PROVIDER=gemini`` with ``GEMINI_API_KEY``).

Answers are always validated against a Pydantic model. Endpoints differ in what they accept (system role,
JSON schema output), so a request that is refused for one of those reasons is retried once in the plainer form
and the endpoint's limits are remembered for the process. Keys are read from the environment, never logged.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

PROVIDER_VARIABLE = "CIR_LLM_PROVIDER"
BASE_URL_VARIABLE = "CIR_LLM_BASE_URL"
MODEL_VARIABLE = "CIR_LLM_MODEL"
KEY_VARIABLE = "CIR_LLM_API_KEY"
GEMINI_KEY_VARIABLE = "GEMINI_API_KEY"
TIMEOUT_VARIABLE = "CIR_LLM_TIMEOUT_SECONDS"
# Requests per minute the client allows itself (the Gemini free tier is about 15 per minute).
RPM_VARIABLE = "CIR_LLM_MAX_REQUESTS_PER_MINUTE"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemma-4-31b-it"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_ATTEMPTS = 6
RETRY_BASE_SECONDS = 2.0

T = TypeVar("T", bound=BaseModel)

# Tests replace this; production uses httpx.
http_post: Callable[..., Any] = httpx.post


class LlmError(RuntimeError):
    """A safe, coded failure; the message never contains prompts, answers or keys."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def provider() -> str:
    value = os.environ.get(PROVIDER_VARIABLE, "").strip().lower()
    if value in ("gemini", "openai", "vllm"):
        return value
    if os.environ.get(BASE_URL_VARIABLE, "").strip():
        return "openai"
    if os.environ.get(GEMINI_KEY_VARIABLE, "").strip():
        return "gemini"
    return "none"


def base_url() -> str:
    configured = os.environ.get(BASE_URL_VARIABLE, "").strip()
    if configured:
        return configured.rstrip("/")
    return GEMINI_BASE_URL if provider() == "gemini" else ""


def model_name() -> str:
    return os.environ.get(MODEL_VARIABLE, "").strip() or DEFAULT_MODEL


def _api_key() -> str:
    return (os.environ.get(KEY_VARIABLE, "").strip()
            or (os.environ.get(GEMINI_KEY_VARIABLE, "").strip() if provider() == "gemini" else ""))


def configured() -> bool:
    """Whether a model endpoint is set up (it may still be unreachable; callers keep their fallback)."""
    if provider() == "none" or not base_url():
        return False
    return provider() in ("openai", "vllm") or bool(_api_key())


def describe() -> dict[str, Any]:
    """What the screen may show about the model: provider and model name, never the key or URL."""
    where = {"gemini": "Gemini API (data sintetis)", "openai": "server model internal", "vllm": "server model internal",
             "none": "tidak dikonfigurasi"}[provider()]
    return {"configured": configured(), "provider": provider(), "model": model_name() if configured() else None,
            "where": where}


# ---- request pacing and endpoint capabilities (per process)
_lock = threading.Lock()
_sent: list[float] = []
_capabilities: dict[str, bool] = {"system_role": True, "json_schema": True}


def _pace() -> None:
    try:
        limit = int(os.environ.get(RPM_VARIABLE, "") or (14 if provider() == "gemini" else 0))
    except ValueError:
        limit = 0
    if limit <= 0:
        return
    while True:
        with _lock:
            now = time.monotonic()
            while _sent and now - _sent[0] > 60:
                _sent.pop(0)
            if len(_sent) < limit:
                _sent.append(now)
                return
            wait = 60 - (now - _sent[0]) + 0.05
        time.sleep(max(0.05, wait))


def reset_state() -> None:
    with _lock:
        _sent.clear()
        _capabilities.update(system_role=True, json_schema=True)


def _json_objects(text: str) -> list[Any]:
    """Every JSON object found in the answer, in order. Models may wrap the answer in a code fence or put their
    reasoning (which can itself quote braces) before it, so each candidate is validated by the caller."""
    text = re.sub(r"<thought>.*?</thought>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<thought>.*$", " ", text, flags=re.DOTALL) if "</thought>" not in text and "<thought>" in text else text
    decoder = json.JSONDecoder()
    found: list[Any] = []
    position = 0
    while True:
        start = text.find("{", position)
        if start < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        position = end


def chat_json(system: str, user: str, schema: type[T], *, max_tokens: int = 2048, temperature: float = 0.0,
              images: list[str] | None = None) -> tuple[T, dict[str, Any]]:
    """Ask once for an answer shaped like ``schema``; returns it with usage metadata (model, seconds, tokens).

    ``images`` are data URLs (``data:image/png;base64,...``) for models that read page images.
    """
    if not configured():
        raise LlmError("LLM_NOT_CONFIGURED")
    url = f"{base_url()}/chat/completions"
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        timeout = float(os.environ.get(TIMEOUT_VARIABLE, "") or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    json_schema = schema.model_json_schema()
    instruction = (f"{system}\n\nJawab HANYA dengan satu objek JSON yang sesuai skema berikut, tanpa teks lain:\n"
                   f"{json.dumps(json_schema, ensure_ascii=False)}")

    def body() -> dict[str, Any]:
        content: Any = user if not images else [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": image}} for image in images]
        if use["system_role"]:
            messages = [{"role": "system", "content": instruction}, {"role": "user", "content": content}]
        else:
            merged = f"{instruction}\n\n---\n\n{user}"
            messages = [{"role": "user", "content": merged if not images else
                         [{"type": "text", "text": merged}] + content[1:]}]
        payload: dict[str, Any] = {"model": model_name(), "messages": messages, "temperature": temperature,
                                   "max_tokens": max_tokens}
        if use["json_schema"]:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "schema": json_schema}}
        return payload

    started = time.monotonic()
    response = None
    use = dict(_capabilities)  # this request's form; plainer forms are tried when the endpoint refuses one
    for _attempt in range(MAX_ATTEMPTS):
        _pace()
        try:
            response = http_post(url, headers=headers, json=body(), timeout=httpx.Timeout(timeout, connect=10.0))
        except httpx.TimeoutException as exc:
            raise LlmError("LLM_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise LlmError("LLM_UNAVAILABLE") from exc
        if response.status_code == 400:
            detail = response.text.lower()
            if use["system_role"] and ("system" in detail or "developer instruction" in detail):
                use["system_role"] = _capabilities["system_role"] = False  # the endpoint never accepts it
                continue
            if use["json_schema"] and ("response_format" in detail or "schema" in detail):
                use["json_schema"] = _capabilities["json_schema"] = False
                continue
            # An unexplained refusal: some endpoints accept simple schemas but not larger ones. The schema is
            # also in the instruction and the answer is validated either way, so retry this request without it.
            if use["json_schema"]:
                use["json_schema"] = False
                continue
            if use["system_role"]:
                use["system_role"] = False
                continue
        # Busy or briefly failing endpoint (shared demo endpoints do this often): wait longer each time.
        if response.status_code in (429, 500, 502, 503, 504) and _attempt < MAX_ATTEMPTS - 1:
            time.sleep(min(30.0, RETRY_BASE_SECONDS * (2 ** _attempt)))
            continue
        break
    assert response is not None
    if response.status_code in (401, 403):
        raise LlmError("LLM_NOT_AUTHORISED")
    if response.status_code == 429:
        raise LlmError("LLM_BUSY")
    if response.status_code >= 400:
        raise LlmError("LLM_UNAVAILABLE")
    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        if isinstance(text, list):  # some endpoints return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmError("LLM_INVALID_ANSWER") from exc
    parsed = None
    for candidate in reversed(_json_objects(text)):  # the answer comes last, after any reasoning
        try:
            parsed = schema.model_validate(candidate)
            break
        except ValidationError:
            continue
    if parsed is None:
        raise LlmError("LLM_INVALID_ANSWER")
    usage = data.get("usage") or {}
    return parsed, {"model": data.get("model") or model_name(), "seconds": round(time.monotonic() - started, 2),
                    "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}
