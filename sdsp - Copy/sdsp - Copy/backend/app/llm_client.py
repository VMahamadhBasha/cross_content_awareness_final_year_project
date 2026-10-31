"""Shared OpenAI-compatible chat completions client."""
import httpx

from app.config import get_settings


def chat_completion_json(
    system_prompt: str, user_prompt: str, image_url: str | None = None
) -> str:
    """Request JSON-mode output, optionally including one vision input."""
    settings = get_settings()
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
