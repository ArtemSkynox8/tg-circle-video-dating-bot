from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    client_id: str
    public_key: str
    guild_id: str
    welcome_channel_id: str


@dataclass(frozen=True)
class DeepSeekConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class OpenAIImageConfig:
    api_key: str
    model: str
    size: str
    quality: str


@dataclass(frozen=True)
class Config:
    discord: DiscordConfig
    deepseek: DeepSeekConfig
    openai_image: OpenAIImageConfig
    data_file: Path
    http_host: str
    http_port: int


config = Config(
    discord=DiscordConfig(
        token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        client_id=os.getenv("DISCORD_CLIENT_ID", "").strip(),
        public_key=os.getenv("DISCORD_PUBLIC_KEY", "").strip(),
        guild_id=os.getenv("DISCORD_GUILD_ID", "").strip(),
        welcome_channel_id=os.getenv("DISCORD_WELCOME_CHANNEL_ID", "").strip(),
    ),
    deepseek=DeepSeekConfig(
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
    ),
    openai_image=OpenAIImageConfig(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip(),
        size=os.getenv("OPENAI_IMAGE_SIZE", "1024x1024").strip(),
        quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium").strip(),
    ),
    data_file=Path(os.getenv("DATA_FILE", "./data/store.json")),
    http_host=os.getenv("HTTP_HOST", "0.0.0.0").strip(),
    http_port=int(os.getenv("PORT", os.getenv("HTTP_PORT", "8080"))),
)


def require_config() -> None:
    missing: list[str] = []
    if not config.discord.token or config.discord.token == "replace_me":
        missing.append("DISCORD_BOT_TOKEN")
    if not config.discord.client_id or config.discord.client_id == "replace_me":
        missing.append("DISCORD_CLIENT_ID")
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
