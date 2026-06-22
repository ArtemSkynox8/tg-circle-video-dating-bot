from __future__ import annotations

import asyncio
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import config
from .content import Character, character_prompt, fallback_reply

logger = logging.getLogger(__name__)


def _request_completion(payload: dict) -> str:
    request = Request(
        f"{config.deepseek.base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {config.deepseek.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:  # noqa: S310 - URL is server configuration
        result = json.load(response)
    return str(result["choices"][0]["message"]["content"]).strip()


async def generate_reply(character: Character, history: list[dict], user_message: str) -> str:
    if not config.deepseek.api_key:
        return fallback_reply(character, user_message)

    messages = [{"role": "system", "content": character_prompt(character)}]
    messages.extend(
        {"role": item["role"], "content": item["content"]}
        for item in history[-16:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    )
    messages.append({"role": "user", "content": user_message})
    payload = {"model": config.deepseek.model, "messages": messages, "temperature": 0.9, "max_tokens": 500}

    try:
        content = await asyncio.to_thread(_request_completion, payload)
        return content or fallback_reply(character, user_message)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        logger.exception("AI reply failed for character %s", character.id)
        return fallback_reply(character, user_message)
