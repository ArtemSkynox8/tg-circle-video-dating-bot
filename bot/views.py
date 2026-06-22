from __future__ import annotations

import discord

from .content import CHARACTERS


class WelcomeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Выбрать девушку", emoji="💌", style=discord.ButtonStyle.primary, custom_id="flow:start")
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .flow import handle_start_request
        await handle_start_request(interaction)

    @discord.ui.button(label="Я не получил DM", style=discord.ButtonStyle.secondary, custom_id="flow:dm_help")
    async def dm_help(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .flow import handle_dm_help
        await handle_dm_help(interaction)


class DmHelpView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Открыть справку Discord", style=discord.ButtonStyle.link, url="https://support.discord.com/hc/en-us/articles/217916488"))

    @discord.ui.button(label="Попробовать снова", style=discord.ButtonStyle.primary, custom_id="flow:retry_dm")
    async def retry(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .flow import handle_retry_dm
        await handle_retry_dm(interaction)


class BeginSelectionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Смотреть анкеты", emoji="💖", style=discord.ButtonStyle.primary, custom_id="flow:browse")
    async def browse(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .flow import handle_browse
        await handle_browse(interaction)


class CharacterPickerView(discord.ui.View):
    def __init__(self, index: int) -> None:
        super().__init__(timeout=None)
        self.index = index % len(CHARACTERS)

        previous = discord.ui.Button(label="Предыдущая", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id=f"character:prev:{self.index}")
        select = discord.ui.Button(label="Выбрать", emoji="💌", style=discord.ButtonStyle.success, custom_id=f"character:select:{self.index}")
        following = discord.ui.Button(label="Следующая", emoji="➡️", style=discord.ButtonStyle.secondary, custom_id=f"character:next:{self.index}")
        previous.callback = self.previous
        select.callback = self.select
        following.callback = self.following
        self.add_item(previous)
        self.add_item(select)
        self.add_item(following)

    async def previous(self, interaction: discord.Interaction) -> None:
        from .flow import handle_move_character
        await handle_move_character(interaction, self.index - 1)

    async def following(self, interaction: discord.Interaction) -> None:
        from .flow import handle_move_character
        await handle_move_character(interaction, self.index + 1)

    async def select(self, interaction: discord.Interaction) -> None:
        from .flow import handle_select_character
        await handle_select_character(interaction, self.index)


class ChangeCharacterView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Выбрать другую девушку", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="flow:change")
    async def change(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .flow import handle_browse
        await handle_browse(interaction)
