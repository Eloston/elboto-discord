# -*- coding: utf-8 -*-

import discord
import discord.ext.typed_commands as commands
from discord.ext.typed_commands import Cog, Context

from elboto.base import Elboto


class Admin(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

    async def cog_check(self, ctx: Context) -> bool:
        # This Cog can only be invoked by the author
        return await self.bot.is_owner(ctx.author)

    @commands.command(hidden=True)
    async def load(self, ctx: Context, *, module: str) -> None:
        """Loads a module."""
        try:
            self.bot.load_extension(module)
        except commands.ExtensionError as exc:
            await ctx.send(f"{exc.__class__.__name__}: {exc}")
        else:
            await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @commands.command(hidden=True)
    async def unload(self, ctx: Context, *, module: str) -> None:
        """Unloads a module."""
        try:
            self.bot.unload_extension(module)
        except commands.ExtensionError as e:
            await ctx.send(f"{e.__class__.__name__}: {e}")
        else:
            await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @commands.command(name="reload", hidden=True)
    async def _reload(self, ctx: Context, *, module: str) -> None:
        """Reloads a module."""
        try:
            try:
                self.bot.reload_extension(module)
            except commands.ExtensionNotLoaded:
                self.bot.reload_extension(f'elboto.cogs.{module}')
        except commands.ExtensionError as exc:
            await ctx.send(f"{exc.__class__.__name__}: {exc}")
        else:
            await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @commands.command(aliases=["invite"])
    async def join(self, ctx: Context) -> None:
        """Joins a server."""
        perms = discord.Permissions.none()
        perms.read_messages = True
        perms.send_messages = True
        perms.embed_links = True
        perms.read_message_history = True
        perms.attach_files = True
        perms.add_reactions = True
        await ctx.send(f"<{discord.utils.oauth_url(self.bot.config.client_id, perms)}>")


def setup(bot: Elboto) -> None:
    bot.add_cog(Admin(bot))
