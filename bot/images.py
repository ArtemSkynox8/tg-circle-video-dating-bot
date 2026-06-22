from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import config
from .content import Character

logger = logging.getLogger(__name__)


def image_prompt(character: Character, user_request: str) -> str:
    request = user_request.strip() or "уютное естественное селфи для собеседника"
    return (
        f"Create a tasteful photorealistic casual photo of an adult woman named {character.name}. "
        f"Her personality is: {character.archetype}. {character.description} "
        f"The requested scene: {request}. Smartphone photo, natural light, believable details, "
        "one adult woman, no text, no watermark, non-explicit, safe-for-work."
    )


def _request_image(prompt: str) -> bytes:
    payload = {
        "model": config.openai_image.model,
        "prompt": prompt,
        "size": config.openai_image.size,
        "quality": config.openai_image.quality,
        "output_format": "jpeg",
    }
    request = Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {config.openai_image.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:  # noqa: S310 - fixed OpenAI endpoint
        result = json.load(response)
    return base64.b64decode(result["data"][0]["b64_json"])


async def generate_photo(character: Character, user_request: str = "") -> bytes | None:
    if not config.openai_image.api_key:
        return None
    try:
        return await asyncio.to_thread(_request_image, image_prompt(character, user_request))
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        logger.exception("Image generation failed for character %s", character.id)
        return None
