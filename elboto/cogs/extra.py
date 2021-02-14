# -*- coding: utf-8 -*-

import discord.ext.typed_commands as commands
from discord.ext.typed_commands import Cog, Context

from elboto.base import Elboto


class Extra(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

    @commands.command(aliases=["hi", "ping", "hey", "whatsup", "yo", "poke"])
    async def hello(self, ctx: Context) -> None:
        await ctx.message.add_reaction("🖖")


def setup(bot: Elboto) -> None:
    bot.add_cog(Extra(bot))


def teardown(bot: Elboto) -> None:
    bot.remove_cog('Extra')
