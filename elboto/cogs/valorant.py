# -*- coding: utf-8 -*-

import io
import json
import sys
import traceback
from typing import Dict, Tuple, cast

import aiohttp
import discord
import discord.ext.typed_commands as commands
from discord.ext.typed_commands import Cog, CommandError, Context

from elboto.base import Elboto
from elboto.utils import DATA_DIR, PersistDictStorage

from .utils.valorant_api import (
    Henrik3APIClient,
    Henrik3APIError,
    RiotAPIClient,
    RiotAPIRegion,
)


def _read_ranks() -> Dict[str, str]:
    with (DATA_DIR / "valorant" / "ranks.json").open() as fp:
        return cast(Dict[str, str], json.load(fp)["Ranks"])


_RANK_NAMES = _read_ranks()


def _print_context(ctx: Context) -> None:
    print(
        f"""=== BEGIN Context ===
Message ({ctx.message.author.name}#{ctx.message.author.discriminator}): {repr(ctx.message.content)}
=== END Context ===
""",
        file=sys.stderr,
    )


def _split_nametag(nametag: str) -> Tuple[str, str]:
    if nametag.count("#") != 1:
        raise ValueError("Nametag must have exactly one #")
    name, tag = nametag.split("#")
    return name, tag


class Valorant(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

        self._persist_dict = PersistDictStorage("valorant")
        self._riot_clients: Dict[RiotAPIRegion, RiotAPIClient] = dict()
        self._henrik3_client = Henrik3APIClient(aiohttp.ClientSession())

    async def cog_check(self, ctx: Context) -> bool:
        # TODO: Open up access to public
        return await self.bot.is_owner(ctx.author)

    def cog_unload(self) -> None:
        for client in self._riot_clients.values():
            self.bot.loop.create_task(client.unload())
        self.bot.loop.create_task(self._henrik3_client.unload())

    async def cog_command_error(self, ctx: Context, error: CommandError) -> None:
        _print_context(ctx)
        traceback.print_exc()
        await ctx.reply(f"Error executing command: `{error}`")

    def _get_backend_client(self, region: RiotAPIRegion) -> RiotAPIClient:
        if region not in self._riot_clients:
            username, password = self.bot.config.valorant_creds[region]
            if username is None or password is None:
                raise CommandError(
                    f"Username or password is invalid for region {region}"
                )
            self._riot_clients[region] = RiotAPIClient(
                aiohttp.ClientSession(), region, username, password
            )
        return self._riot_clients[region]

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

    @valo.command(hidden=True)
    async def rank_puuid(self, ctx: Context, region: RiotAPIRegion, puuid: str) -> None:
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

    @valo.command()
    async def rank(self, ctx: Context, nametag: str) -> None:
        try:
            data = self._persist_dict.read_json(nametag)
        except KeyError:
            ctx.reply(
                f"Unable to find `{nametag}` (case-sensitive). Please check that it is registered."
            )
        region = RiotAPIRegion(data["region"])
        assert isinstance(data["puuid"], str)
        puuid = data["puuid"]
        await self.rank_puuid(ctx, region, puuid)

    def _store_puuid(self, nametag: str, region: RiotAPIRegion, puuid: str) -> None:
        self._persist_dict.store_json(nametag, dict(region=region, puuid=puuid))

    @valo.command(hidden=True)
    async def register_puuid(
        self, ctx: Context, nametag: str, region: RiotAPIRegion, puuid: str
    ) -> None:
        self._store_puuid(nametag, region, puuid)
        await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @valo.command()
    async def register(self, ctx: Context, region: RiotAPIRegion, nametag: str) -> None:
        async with ctx.typing():
            try:
                name, tag = nametag.split("#")
            except ValueError as exc:
                await ctx.reply(f"Invalid nametag: `{exc}`")
                return
            try:
                puuid = await self._henrik3_client.get_puuid(name, tag)
            except Henrik3APIError as exc:
                if exc.code == 429:
                    await ctx.reply(
                        f"""Exceeded rate limit to get PUUID. Please take these steps instead:
1. Copy `puuid` field from: {self._henrik3_client.get_puuid_url(name, tag)}
2. Run the following command (replacing `PUUID_HERE`): `{ctx.prefix}{self.register_puuid.qualified_name} {nametag} {region.value} PUUID_HERE`"""
                    )
                    return
            self._store_puuid(nametag, region, puuid)
            await ctx.message.add_reaction("\N{OK HAND SIGN}")


def setup(bot: Elboto) -> None:
    bot.add_cog(Valorant(bot))


def teardown(bot: Elboto) -> None:
    bot.remove_cog("Valorant")
