from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import config
from .content import Character

logger = logging.getLogger(__name__)
BASE_ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets" / "base"


def character_base_path(character: Character) -> Path:
    path = BASE_ASSET_ROOT / f"{character.name}.png"
    if not path.is_file():
        raise FileNotFoundError(f"Base character image not found: {path}")
    return path


def image_prompt(character: Character, user_request: str) -> str:
    request = user_request.strip() or "уютное естественное селфи для собеседника"
    return (
        "Use the supplied reference image as the identity source. Preserve the exact same adult woman's "
        "recognizable face, facial structure, hair identity and overall appearance. Do not copy the original "
        "background, clothes, pose, camera angle or composition unless the requested scene needs them. "
        f"This character is {character.name}, {character.archetype}. Scene: {request}. "
        "Choose a new natural pose, suitable clothes and a believable environment for that scene. "
        "Make it look like a fresh casual smartphone photo, photorealistic, natural light, one adult woman, "
        "no text, no watermark, non-explicit and safe-for-work."
    )


def _multipart_body(character: Character, prompt: str) -> tuple[bytes, str]:
    boundary = f"----CodexPhoto{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ))

    field("model", config.openai_image.model)
    field("prompt", prompt)
    field("size", config.openai_image.size)
    field("quality", config.openai_image.quality)
    field("output_format", "jpeg")
    field("input_fidelity", "high")

    source = character_base_path(character)
    chunks.extend((
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{source.name}"\r\n'.encode(),
        b"Content-Type: image/png\r\n\r\n",
        source.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    return b"".join(chunks), boundary


def _request_image(character: Character, prompt: str) -> bytes:
    body, boundary = _multipart_body(character, prompt)
    request = Request(
        "https://api.openai.com/v1/images/edits",
        data=body,
        headers={
            "Authorization": f"Bearer {config.openai_image.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=180) as response:  # noqa: S310 - fixed OpenAI endpoint
        result = json.load(response)
    return base64.b64decode(result["data"][0]["b64_json"])


async def generate_photo(character: Character, user_request: str = "") -> bytes | None:
    if not config.openai_image.api_key:
        return None
    try:
        return await asyncio.to_thread(_request_image, character, image_prompt(character, user_request))
    except (HTTPError, URLError, TimeoutError, FileNotFoundError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        logger.exception("Image edit failed for character %s", character.id)
        return None
