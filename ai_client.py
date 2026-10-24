"""Thin wrapper around any OpenAI-compatible Chat Completions API.

Works with OpenAI, Azure OpenAI-compatible gateways, Groq, Together,
OpenRouter, Ollama, LM Studio and anything else that speaks the
``/chat/completions`` protocol.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import requests

import config


class AIError(Exception):
    """A user-friendly error raised by the AI layer."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def provider_info() -> dict[str, Any]:
    """Describe the current connection for the frontend status badge."""
    active = config.get_active_provider()
    providers = config.available_providers()
    # The selected model may belong to a different provider than the active one.
    connection = config.resolve_connection(config.get_default_model())
    model_provider = connection.get("provider", active)
    active_entry = next((p for p in providers if p["id"] == model_provider), None)
    configured = bool(connection.get("api_key")) or bool(
        connection.get("custom") and connection.get("base_url")
    )
    return {
        "configured": configured,
        "model": config.get_default_model(),
        "models": config.get_models(),
        "base_url": config.get_base_url(),
        "provider": active,
        "model_provider": model_provider,
        "provider_name": (active_entry or {}).get("name", model_provider),
        "providers": providers,
        "catalog_updated": config.CATALOG_UPDATED,
        "reasoning_levels": config.REASONING_LEVELS,
        "reasoning_effort": config.get_reasoning_effort(),
    }


def _guess_reasoning(model_id: str) -> bool:
    """Best-effort guess that a model supports a thinking/reasoning mode."""
    text = (model_id or "").lower()
    markers = (
        "o1", "o3", "o4", "reason", "thinking", "think", "r1", "qvq",
        "gpt-5", "gpt-6", "claude-opus", "claude-sonnet", "claude-haiku",
        "gemini-3", "gemini-2.5", "grok-4", "grok-3", "glm-4.7", "glm-5",
        "deepseek-v4-pro", "kimi-k2-thinking", "qwen3-max-thinking",
    )
    return any(marker in text for marker in markers)


def fetch_models(provider: str | None = None) -> list[dict[str, Any]]:
    """Fetch the live model list from a provider's ``/models`` endpoint.

    Works with any OpenAI-compatible endpoint. The result is normalised and
    cached so it survives restarts. Raises :class:`AIError` on failure.
    """
    provider = provider or config.get_active_provider()
    base_url = config.get_provider_base_url(provider)
    if not base_url:
        raise AIError("This provider has no base URL configured yet.", status=400)
    api_key = config.get_provider_key(provider)

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/models",
            headers=headers,
            timeout=20,
        )
    except requests.exceptions.RequestException as exc:
        raise AIError(f"Could not reach {base_url} to list models: {exc}") from exc

    if response.status_code != 200:
        raise _error_from_response(response)

    try:
        payload = response.json()
    except ValueError as exc:
        raise AIError("The provider returned an unexpected (non-JSON) model list.") from exc

    raw = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise AIError("The provider did not return a model list.")

    models: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id.endswith(":batch"):
            continue
        label = str(item.get("label") or item.get("name") or model_id)
        context = item.get("context_length") or item.get("context_window") or 0
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        free = model_id.endswith(":free") or (
            pricing.get("prompt") in (0, "0", "0.0") and pricing.get("completion") in (0, "0", "0.0")
        )
        models.append(
            {
                "id": model_id,
                "label": label,
                "hint": str(item.get("blurb") or item.get("description") or "").strip(),
                "badge": "Free" if free else "",
                "reasoning": _guess_reasoning(model_id),
                "context": int(context or 0),
            }
        )

    if not models:
        raise AIError("The provider returned an empty model list.")
    models.sort(key=lambda m: ("Free" not in m["badge"], m["label"].lower()))
    config.save_catalog(provider, models)
    return models


def _connection(model: str | None) -> dict[str, Any]:
    """Resolve base URL, key and model metadata for a model id."""
    chosen_model = (model or config.get_default_model()).strip()
    connection = config.resolve_connection(chosen_model)
    return {
        "model": chosen_model,
        "base_url": connection["base_url"],
        "api_key": connection["api_key"],
        "provider": connection["provider"],
        "meta": connection.get("model") or {},
        "custom": bool(connection.get("custom")),
    }


def _endpoint(base_url: str) -> str:
    return f"{base_url}/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    # Local / self-hosted OpenAI-compatible servers often need no key at all.
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _error_from_response(response: requests.Response) -> AIError:
    """Turn a failed HTTP response into a readable AIError."""
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message", ""))
            elif error:
                detail = str(error)
            elif payload.get("message"):
                detail = str(payload["message"])
    except ValueError:
        detail = (response.text or "").strip()[:400]

    if response.status_code == 401:
        base = "That API key was rejected. Please double-check it and try again."
    elif response.status_code == 403:
        base = "Access denied. Your key may not have permission for this model."
    elif response.status_code == 404:
        base = "The model or endpoint was not found. Check the model name and base URL."
    elif response.status_code == 429:
        base = "Rate limit or quota reached. Please wait a moment and try again."
    elif response.status_code >= 500:
        base = "The AI provider had a server problem. Please try again shortly."
    else:
        base = f"The AI provider returned HTTP {response.status_code}."
    return AIError(f"{base}{(' ' + detail) if detail else ''}", status=502)


def _clean_messages(messages: Any) -> list[dict[str, Any]]:
    """Validate and trim the conversation sent by the client.

    Keeps tool-use turns intact so the agent loop can feed tool results back
    to the provider.
    """
    if not isinstance(messages, list) or not messages:
        raise AIError("Please send at least one message.", status=400)
    if len(messages) > 100:
        raise AIError("This conversation is too long (max 100 messages).", status=400)

    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")

        # Tool results produced by the agent loop.
        if role == "tool":
            cleaned.append(
                {
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id") or "",
                    "content": (content or "")[:32000] if isinstance(content, str) else "",
                }
            )
            continue

        # An assistant turn that requested one or more tools.
        if role == "assistant" and message.get("tool_calls"):
            cleaned.append(
                {
                    "role": "assistant",
                    "content": content if isinstance(content, str) else "",
                    "tool_calls": message["tool_calls"],
                }
            )
            continue

        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:32000]})

    if not cleaned:
        raise AIError("No usable messages were found in the request.", status=400)
    return cleaned


def _payload(
    messages: list[dict[str, Any]],
    model: str,
    stream: bool,
    *,
    meta: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "stream": stream,
    }
    # Reasoning models accept a thinking level via ``reasoning_effort``.
    # ``off`` stays out of the payload so the provider keeps its own default.
    if meta.get("reasoning"):
        effort = (reasoning_effort or config.get_reasoning_effort() or "").lower()
        if effort and effort != "off":
            payload["reasoning_effort"] = effort
    # Workspace tools (OpenAI function-calling schema).
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    return payload


def stream_chat(
    messages: Any,
    model: str | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield ``{"type": ...}`` deltas as they arrive.

    ``type`` is ``"reasoning"`` (the model's thinking), ``"content"`` (the
    visible answer) or ``"tool_calls"`` (a completed list of tool calls the
    caller should execute before continuing).
    """
    connection = _connection(model)
    if not connection["api_key"] and not (connection.get("custom") and connection["base_url"]):
        raise AIError(
            "No API key configured. Add one in Settings, or set OPENAI_API_KEY and restart.",
            status=400,
        )

    cleaned = _clean_messages(messages)
    chosen_model = connection["model"]
    want_thinking = bool(connection["meta"].get("reasoning"))

    try:
        response = requests.post(
            _endpoint(connection["base_url"]),
            headers=_headers(connection["api_key"]),
            json=_payload(
                cleaned,
                chosen_model,
                stream=True,
                meta=connection["meta"],
                reasoning_effort=reasoning_effort,
                tools=tools,
            ),
            stream=True,
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout as exc:
        raise AIError("The request timed out. Please try again.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise AIError(f"Could not reach the AI provider at {connection['base_url']}.") from exc
    except requests.exceptions.RequestException as exc:
        raise AIError(f"Network error while contacting the AI provider: {exc}") from exc

    with response:
        if response.status_code != 200:
            raise _error_from_response(response)

        produced = False
        # Tool calls stream in fragments; accumulate them by index.
        pending_calls: dict[int, dict[str, Any]] = {}
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                if line == "[DONE]":
                    break
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue

            if isinstance(event, dict) and event.get("error"):
                error = event["error"]
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise AIError(f"The AI provider reported an error: {message}")

            for choice in event.get("choices", []) if isinstance(event, dict) else []:
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    produced = True
                    yield {"type": "content", "text": piece}
                # Only surface thinking for models flagged as reasoning-capable.
                if want_thinking:
                    thinking = delta.get("reasoning_content") or delta.get("reasoning")
                    if thinking:
                        produced = True
                        yield {"type": "reasoning", "text": thinking}

                # Native tool calls (current OpenAI schema).
                for tool_call in delta.get("tool_calls") or []:
                    index = tool_call.get("index", 0)
                    slot = pending_calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tool_call.get("id"):
                        slot["id"] = tool_call["id"]
                    function = tool_call.get("function") or {}
                    slot["function"]["name"] += function.get("name") or ""
                    slot["function"]["arguments"] += function.get("arguments") or ""

                # Legacy single-function schema.
                legacy = delta.get("function_call")
                if legacy:
                    slot = pending_calls.setdefault(
                        0, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                    )
                    slot["function"]["name"] += legacy.get("name") or ""
                    slot["function"]["arguments"] += legacy.get("arguments") or ""

        if pending_calls:
            calls = [pending_calls[key] for key in sorted(pending_calls)]
            for position, call in enumerate(calls):
                if not call["id"]:
                    call["id"] = f"call_{position}"
            yield {"type": "tool_calls", "calls": calls}
            return

        if not produced:
            # Some providers ignore stream=True and send a normal body.
            fallback = _complete_once(
                cleaned,
                chosen_model,
                connection["api_key"],
                base_url=connection["base_url"],
                meta=connection["meta"],
                reasoning_effort=reasoning_effort,
                tools=tools,
            )
            if fallback["tool_calls"]:
                calls = fallback["tool_calls"]
                for position, call in enumerate(calls):
                    if not call.get("id"):
                        call["id"] = f"call_{position}"
                yield {"type": "tool_calls", "calls": calls}
                return
            if fallback["reasoning"] and want_thinking:
                yield {"type": "reasoning", "text": fallback["reasoning"]}
            if fallback["reply"]:
                yield {"type": "content", "text": fallback["reply"]}


def _complete_once(
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    *,
    base_url: str | None = None,
    meta: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        response = requests.post(
            _endpoint(base_url or config.get_base_url()),
            headers={**_headers(api_key), "Accept": "application/json"},
            json=_payload(
                messages,
                model,
                stream=False,
                meta=meta,
                reasoning_effort=reasoning_effort,
                tools=tools,
            ),
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise AIError(f"Network error while contacting the AI provider: {exc}") from exc

    if response.status_code != 200:
        raise _error_from_response(response)

    try:
        data = response.json()
        message = data["choices"][0]["message"] or {}
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        return {
            "reply": message.get("content") or "",
            "reasoning": reasoning,
            "tool_calls": message.get("tool_calls") or [],
        }
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError(f"Unexpected response from the AI provider: {exc}") from exc


def complete_chat(
    messages: Any,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Non-streaming completion. Returns reply, model and any reasoning."""
    connection = _connection(model)
    if not connection["api_key"] and not (connection.get("custom") and connection["base_url"]):
        raise AIError(
            "No API key configured. Add one in Settings, or set OPENAI_API_KEY and restart.",
            status=400,
        )
    cleaned = _clean_messages(messages)
    chosen_model = connection["model"]
    result = _complete_once(
        cleaned,
        chosen_model,
        connection["api_key"],
        base_url=connection["base_url"],
        meta=connection["meta"],
        reasoning_effort=reasoning_effort,
    )
    return {
        "reply": result["reply"],
        "reasoning": result["reasoning"] if connection["meta"].get("reasoning") else "",
        "model": chosen_model,
        "provider": connection["provider"],
    }