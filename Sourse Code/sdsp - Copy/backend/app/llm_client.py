"""Shared JSON chat client for OpenAI-compatible APIs and Gemini."""
import base64
import re

import httpx

from app.config import get_settings


def _gemini_content(user_prompt: str, image_url: str | None) -> list[dict]:
    parts = [{"text": user_prompt}]
    if image_url:
        match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,(.+)", image_url, re.DOTALL)
        if not match:
            raise ValueError("Gemini image input must be a base64 JPEG, PNG, or WebP data URL.")
        mime_type, encoded = match.groups()
        try:
            base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Gemini image input is not valid base64.") from exc
        parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
    return parts


def _gemini_chat(
    system_prompt: str, user_prompt: str, image_url: str | None
) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent",
        params={"key": settings.gemini_api_key},
        json={
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": _gemini_content(user_prompt, image_url)}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()
    try:
        content = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not contain a text completion.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Gemini returned an empty completion.")
    return content


def chat_completion_json(
    system_prompt: str, user_prompt: str, image_url: str | None = None
) -> str:
    """Request JSON-mode output from the configured provider."""
    settings = get_settings()
    if getattr(settings, "llm_backend", "openai") == "gemini":
        return _gemini_chat(system_prompt, user_prompt, image_url)
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    content: str | list[dict] = user_prompt
    if image_url:
        content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}},
        ]
    response = httpx.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={
            "model": settings.openai_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("OpenAI response did not contain a chat completion.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenAI returned an empty chat completion.")
    return content
