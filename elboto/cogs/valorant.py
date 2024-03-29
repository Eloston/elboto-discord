# -*- coding: utf-8 -*-

import asyncio
import functools
import io
import json
import sys
import traceback
from typing import Dict, Optional, Tuple, cast

import discord
import discord.ext.typed_commands as commands
from discord.ext.typed_commands import Cog, CommandError, Context

from elboto.base import Elboto
from elboto.utils import DATA_DIR, PersistDictStorage

from .utils.valorant_api import (Henrik3APIClient, Henrik3APIError,
                                 RiotAPIClient, RiotAPIRegion)


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


def _join_nametag(name: str, tag: str) -> str:
    return f"{name}#{tag}"


def _is_guild_owner(ctx: Context) -> bool:
    return ctx.guild is not None and ctx.guild.owner_id == ctx.author.id


class Valorant(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

        self._persist_dict = PersistDictStorage("valorant")
        self._riot_clients: Dict[RiotAPIRegion, RiotAPIClient] = dict()
        self._henrik3_client = Henrik3APIClient()

    def _has_guild_roles(self, ctx: Context) -> bool:
        if not isinstance(ctx.channel, discord.abc.GuildChannel) or not isinstance(
            ctx.author, discord.Member
        ):
            return False

        getter = functools.partial(discord.utils.get, ctx.author.roles)
        if any(
            getter(id=item) is not None
            if isinstance(item, int)
            else getter(name=item) is not None
            for item in self.bot.config.valorant_access_roles
        ):
            return True
        return False

    async def cog_check(self, ctx: Context) -> bool:
        return (
            await self.bot.is_owner(ctx.author)
            or _is_guild_owner(ctx)
            or self._has_guild_roles(ctx)
        )

    def cog_unload(self) -> None:
        for client in self._riot_clients.values():
            asyncio.run_coroutine_threadsafe(client.unload(), self.bot.loop)

    async def cog_command_error(self, ctx: Context, error: CommandError) -> None:
        _print_context(ctx)
        traceback.print_exc()

    def _get_backend_client(self, region: RiotAPIRegion) -> RiotAPIClient:
        if region not in self._riot_clients:
            username, password = self.bot.config.valorant_creds[region]
            if username is None or password is None:
                raise CommandError(
                    f"Username or password is invalid for region {region}"
                )
            self._riot_clients[region] = RiotAPIClient(region, username, password)
        return self._riot_clients[region]

    @commands.group(aliases=["valorant", "val"], invoke_without_command=True)
    async def valo(self, ctx: Context) -> None:
        await ctx.reply("valo: Invalid subcommand")

    @valo.group(name="admin", hidden=True)
    @commands.is_owner()
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

    @valo_admin.command()
    async def list(self, ctx: Context, *, region: Optional[RiotAPIRegion] = None) -> None:
        filtered_nametags = None
        msg = ""
        if region is None:
            msg = "All registrations:\n"
            filtered_nametags = self._persist_dict.keys()
        else:
            msg = f"Registrations in {region.upper()}:\n"
            filtered_nametags = tuple(filter(lambda x: self._persist_dict.read_json(x)["region"] == region, self._persist_dict.keys()))
        if filtered_nametags:
            await ctx.reply(msg + "\n".join(f"`{nametag}`" for nametag in sorted(filtered_nametags)))
        else:
            await ctx.reply(msg + "No registered nametags")

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
        if nametag not in self._persist_dict.keys():
            await self.register(ctx, nametag)
        try:
            data = self._persist_dict.read_json(nametag)
        except KeyError:
            # Registration still failed, and registration printed error message already.
            return
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
    async def register(self, ctx: Context, nametag: str) -> None:
        async with ctx.typing():
            try:
                name, tag = _split_nametag(nametag)
            except ValueError as exc:
                await ctx.reply(f"Invalid nametag: `{exc}`")
                return
            try:
                region, puuid = await self._henrik3_client.get_puuid(name, tag)
            except Henrik3APIError as exc:
                if exc.code == 429:
                    await ctx.reply(
                        f"""Exceeded rate limit to get PUUID. Please take these steps instead:
1. Copy `puuid` field from: {self._henrik3_client.get_account_url(name, tag)}
2. Run the following command (replacing `PUUID_HERE`): `{ctx.prefix}{self.register_puuid.qualified_name} {nametag} {region.value} PUUID_HERE`"""
                    )
                    return
                raise exc
            await self.register_puuid(ctx, nametag, region, puuid)

    @valo.command()
    async def register_creds(
        self, ctx: Context, region: RiotAPIRegion, username: str, password: str
    ) -> None:
        riot_client = RiotAPIClient(region, username, password)
        name, tag = await riot_client.get_nametag()
        puuid = await riot_client.get_puuid()
        nametag = _join_nametag(name, tag)
        await self.register_puuid(ctx, nametag, region, puuid)
        await ctx.reply(f"Registered {nametag} in region {region}")
        await riot_client.unload()


def setup(bot: Elboto) -> None:
    bot.add_cog(Valorant(bot))


def teardown(bot: Elboto) -> None:
    bot.remove_cog("Valorant")
