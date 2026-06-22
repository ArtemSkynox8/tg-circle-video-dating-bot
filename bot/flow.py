from __future__ import annotations

from io import BytesIO
from pathlib import Path

import discord

from .ai import generate_reply
from .content import CHARACTER_BY_ID, CHARACTERS, Character
from .images import generate_photo
from .store import add_event, get_user, update_store, upsert_user, utc_now
from .views import BeginSelectionView, ChangeCharacterView, CharacterPickerView, DmHelpView, WelcomeView

ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets" / "questions"


def welcome_embed() -> discord.Embed:
    return discord.Embed(title="Найди свою AI-девушку", description="Знакомство и личное общение проходят в DM. Нажми кнопку ниже — я пришлю анкеты девушек в личку.", color=0xFF5F8F)


def dm_closed_text() -> str:
    return "\n".join(("Я не смогла написать тебе в личку.", "", "Включи личные сообщения от участников сервера:", "Server Settings → Privacy Settings → Allow direct messages from server members.", "", "Потом нажми «Попробовать снова» или напиши боту `/start` в DM."))


def character_embed(character: Character, index: int, filename: str) -> discord.Embed:
    embed = discord.Embed(
        title=character.display_name,
        description=f"**{character.archetype}**\n\n{character.description}\n\nАнкета {index + 1}/{len(CHARACTERS)}",
        color=0xFF5F8F,
    )
    embed.set_footer(text="Листай анкеты или выбери девушку, чтобы начать общение")
    embed.set_image(url=f"attachment://{filename}")
    return embed


def character_card(index: int) -> tuple[discord.Embed, discord.File, CharacterPickerView]:
    normalized = index % len(CHARACTERS)
    character = CHARACTERS[normalized]
    path = ASSET_ROOT / character.video_filename
    if not path.is_file():
        raise FileNotFoundError(f"Character video not found: {path}")
    file = discord.File(path, filename=character.video_filename)
    return character_embed(character, normalized, file.filename), file, CharacterPickerView(normalized)


async def send_welcome(destination: discord.abc.Messageable) -> None:
    await destination.send(embed=welcome_embed(), view=WelcomeView())


async def send_member_dm_welcome(member: discord.Member) -> bool:
    try:
        dm = await member.create_dm()
        await dm.send(embed=discord.Embed(title="Добро пожаловать 💖", description="Здесь ты можешь посмотреть видео-анкеты и выбрать девушку с характером, который подходит именно тебе.", color=0xFF5F8F), view=BeginSelectionView())
        return True
    except discord.Forbidden as error:
        await add_event("member_dm_welcome_failed", {"user_id": str(member.id), "error": str(error)})
        return False


async def send_selection_invite(user: discord.User | discord.Member) -> None:
    dm = await user.create_dm()
    await upsert_user(user.id, {"step": "selecting", "dm_channel_id": str(dm.id), "character_index": 0})
    embed = discord.Embed(title="Кто тебе понравится?", description="У каждой девушки свой характер. Посмотри видео-анкеты и выбери ту, с которой захочется продолжить знакомство.", color=0xFF5F8F)
    await dm.send(embed=embed, view=BeginSelectionView())


async def handle_start_request(interaction: discord.Interaction) -> None:
    await add_event("start_clicked", {"user_id": str(interaction.user.id), "guild_id": str(interaction.guild_id or "")})
    try:
        await send_selection_invite(interaction.user)
    except discord.Forbidden as error:
        await add_event("dm_start_failed", {"user_id": str(interaction.user.id), "error": str(error)})
        await interaction.response.send_message(dm_closed_text(), view=DmHelpView(), ephemeral=True)
        return
    message = "Я отправила тебе приглашение в личку 💌"
    await interaction.response.send_message(message, ephemeral=interaction.guild_id is not None)


async def handle_retry_dm(interaction: discord.Interaction) -> None:
    await handle_start_request(interaction)


async def handle_dm_help(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(dm_closed_text(), view=DmHelpView(), ephemeral=True)


async def handle_browse(interaction: discord.Interaction) -> None:
    user = await get_user(interaction.user.id)
    index = int((user or {}).get("character_index", 0)) % len(CHARACTERS)
    await upsert_user(interaction.user.id, {"step": "selecting", "character_index": index})
    embed, file, view = character_card(index)
    await interaction.response.send_message(embed=embed, file=file, view=view)


async def handle_move_character(interaction: discord.Interaction, index: int) -> None:
    normalized = index % len(CHARACTERS)
    await upsert_user(interaction.user.id, {"step": "selecting", "character_index": normalized})
    embed, file, view = character_card(normalized)
    await interaction.response.edit_message(embed=embed, attachments=[file], view=view)


async def handle_select_character(interaction: discord.Interaction, index: int) -> None:
    normalized = index % len(CHARACTERS)
    character = CHARACTERS[normalized]
    await upsert_user(interaction.user.id, {"step": "chat", "character_id": character.id, "character_index": normalized, "chat_history": [{"role": "assistant", "content": character.opener}], "last_message_at": utc_now()})
    await add_event("character_selected", {"user_id": str(interaction.user.id), "character_id": character.id})
    await interaction.response.edit_message(view=None)
    await interaction.followup.send(f"**{character.display_name}**\n{character.opener}", view=ChangeCharacterView())


async def handle_dm_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    user = await get_user(message.author.id)
    if not user or user.get("step") != "chat":
        await send_selection_invite(message.author)
        return
    character = CHARACTER_BY_ID.get(str(user.get("character_id", "")))
    if not character:
        await send_selection_invite(message.author)
        return
    async with message.channel.typing():
        reply = await generate_reply(character, list(user.get("chat_history", [])), message.content)

    def mutate(data: dict) -> None:
        stored = data["users"][str(message.author.id)]
        stored["chat_history"] = [*stored.get("chat_history", []), {"role": "user", "content": message.content}, {"role": "assistant", "content": reply}][-30:]
        stored["last_message_at"] = utc_now()

    await update_store(mutate)
    await message.reply(reply)


async def handle_generate_photo(interaction: discord.Interaction, prompt: str = "") -> None:
    user = await get_user(interaction.user.id)
    character = CHARACTER_BY_ID.get(str((user or {}).get("character_id", "")))
    if not character:
        await interaction.response.send_message("Сначала выбери девушку.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    image = await generate_photo(character, prompt)
    if image is None:
        await interaction.followup.send("Не получилось создать фото. Проверь `OPENAI_API_KEY` или попробуй ещё раз чуть позже.")
        return
    filename = f"{character.id}-photo.jpg"
    await add_event("photo_generated", {"user_id": str(interaction.user.id), "character_id": character.id})
    await interaction.followup.send(
        content=f"**{character.display_name}**\nДержи 📸",
        file=discord.File(BytesIO(image), filename=filename),
        view=ChangeCharacterView(),
    )
