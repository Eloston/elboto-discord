# -*- coding: utf-8 -*-

import io
import json
from typing import Dict, cast

import aiohttp
import discord
import discord.ext.typed_commands as commands
from discord.ext.typed_commands import Cog, CommandError, Context

from elboto.base import Elboto
from elboto.utils import DATA_DIR, PersistDictStorage

from .utils.valorant_api import RiotAPIClient, RiotAPIRegion


def _read_ranks() -> Dict[str, str]:
    with (DATA_DIR / "valorant" / "ranks.json").open() as fp:
        return cast(Dict[str, str], json.load(fp)["Ranks"])


_RANK_NAMES = _read_ranks()


class Valorant(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

        self._persist_dict = PersistDictStorage("valorant")
        self._clients: Dict[RiotAPIRegion, RiotAPIClient] = dict()

    async def cog_check(self, ctx: Context) -> bool:
        # TODO: Open up access to public
        return await self.bot.is_owner(ctx.author)

    def cog_unload(self) -> None:
        for client in self._clients.values():
            self.bot.loop.create_task(client.unload())

    async def cog_command_error(self, ctx: Context, error: CommandError) -> None:
        await ctx.reply(f"Error executing command: `{error}`")

    def _get_backend_client(self, region: RiotAPIRegion) -> RiotAPIClient:
        if region not in self._clients:
            username, password = self.bot.config.valorant_creds[region]
            if username is None or password is None:
                raise CommandError(
                    f"Username or password is invalid for region {region}"
                )
            self._clients[region] = RiotAPIClient(
                aiohttp.ClientSession(), region, username, password
            )
        return self._clients[region]

    @commands.group()
    async def valo(self, ctx: Context) -> None:
        pass

    @valo.group(name="admin", hidden=True)
    async def valo_admin(self, ctx: Context) -> None:
        pass

    @valo_admin.command()
    async def forcerefresh(self, ctx: Context, region: RiotAPIRegion) -> None:
        async with ctx.typing():
            await self._get_backend_client(region).refresh_tokens(True)
            await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @valo_admin.command()
    async def userinfo(self, ctx: Context, region: RiotAPIRegion) -> None:
        async with ctx.typing():
            data = await self._get_backend_client(region).get_userinfo()
            await ctx.reply(f"""```json\n{json.dumps(data, indent=2)}\n```""")

    @valo.command()
    async def mmr(
        self,
        ctx: Context,
        region: RiotAPIRegion,
        puuid: str,
        start_index: int,
        end_index: int,
    ) -> None:
        async with ctx.typing():
            data = await self._get_backend_client(region).get_mmr(
                puuid, start_index, end_index
            )
            data_io = io.BytesIO(json.dumps(data, indent=2).encode("UTF-8"))
            await ctx.reply(
                "See attachment", file=discord.File(data_io, f"mmr_{puuid}.json")
            )

    @valo.command()
    async def rank(self, ctx: Context, region: RiotAPIRegion, puuid: str) -> None:
        async with ctx.typing():
            data = await self._get_backend_client(region).get_current_compet_stats(
                puuid
            )
            if data is None:
                await ctx.reply("Unable to find rank data from match history")
            else:
                tier, ranked_rating, match_start_time = data
                await ctx.reply(
                    f"""Rank: {_RANK_NAMES[str(tier)]}
Ranked Rating: {ranked_rating}
Updated (UTC): {match_start_time.strftime('%c')}"""
                )


def setup(bot: Elboto) -> None:
    bot.add_cog(Valorant(bot))


def teardown(bot: Elboto) -> None:
    bot.remove_cog("Valorant")
