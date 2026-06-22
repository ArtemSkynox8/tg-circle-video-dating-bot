from __future__ import annotations

import asyncio
import logging

import discord
from aiohttp import web
from discord import app_commands

from .config import config, require_config
from .content import CHARACTERS
from .flow import handle_dm_help, handle_dm_message, handle_generate_photo, handle_start_request, send_member_dm_welcome, send_welcome
from .views import BeginSelectionView, ChangeCharacterView, CharacterPickerView, DmHelpView, WelcomeView

BOT_PERMISSIONS = 84992
logger = logging.getLogger(__name__)


async def health_response(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "discord_ready": client.is_ready()})


def invite_url() -> str:
    return "https://discord.com/oauth2/authorize" f"?client_id={config.discord.client_id}" "&scope=bot%20applications.commands" f"&permissions={BOT_PERMISSIONS}"


class AiGirlBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.dm_messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.add_view(WelcomeView())
        self.add_view(DmHelpView())
        self.add_view(BeginSelectionView())
        self.add_view(ChangeCharacterView())
        for index in range(len(CHARACTERS)):
            self.add_view(CharacterPickerView(index))

        if config.discord.guild_id:
            guild = discord.Object(id=int(config.discord.guild_id))
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                print(f"Synced slash commands to guild {config.discord.guild_id}")
            except discord.Forbidden:
                print(f"Cannot sync guild commands. Invite URL: {invite_url()}")
                await self.tree.sync()
        else:
            await self.tree.sync()

client = AiGirlBot()


@client.event
async def on_ready() -> None:
    assert client.user is not None
    print(f"Discord bot logged in as {client.user} ({client.user.id})")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        if message.content.strip().lower() == "/start":
            await handle_start_request_from_dm(message)
            return
        await handle_dm_message(message)


async def handle_start_request_from_dm(message: discord.Message) -> None:
    from .flow import send_selection_invite
    await send_selection_invite(message.author)


@client.event
async def on_member_join(member: discord.Member) -> None:
    if config.discord.guild_id and str(member.guild.id) != config.discord.guild_id:
        return
    await send_member_dm_welcome(member)


@client.tree.command(name="start", description="Открыть видео-анкеты девушек в личных сообщениях")
async def start_command(interaction: discord.Interaction) -> None:
    await handle_start_request(interaction)


@client.tree.command(name="dm-help", description="Что делать, если бот не может написать в личку")
async def dm_help_command(interaction: discord.Interaction) -> None:
    await handle_dm_help(interaction)


@client.tree.command(name="photo", description="Попросить выбранную девушку прислать фото")
@app_commands.describe(description="Какое фото ты хочешь получить")
async def photo_command(interaction: discord.Interaction, description: str = "") -> None:
    await handle_generate_photo(interaction, description)


@client.tree.command(name="welcome-preview", description="Опубликовать стартовое сообщение в текущем канале")
async def welcome_preview_command(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Стартовое сообщение опубликовано.", ephemeral=True)
    if interaction.channel:
        await send_welcome(interaction.channel)  # type: ignore[arg-type]


async def run_bot() -> None:
    app = web.Application()
    app.router.add_get("/", health_response)
    app.router.add_get("/healthz", health_response)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, config.http_host, config.http_port).start()
    print(f"Health server started on {config.http_host}:{config.http_port}", flush=True)
    try:
        await client.start(config.discord.token)
    finally:
        await runner.cleanup()


def main() -> None:
    require_config()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
