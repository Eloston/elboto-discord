# -*- coding: utf-8 -*-

import datetime
import enum
import io
import json
import sys
import urllib.parse
from typing import Any, Dict, Optional, Tuple, cast

import discord
import discord.ext.typed_commands as commands
from aiohttp import ClientSession
from discord.ext.typed_commands import Cog, CommandError, Context

from elboto.base import Elboto
from elboto.utils import DATA_DIR

# We need to use the undocumented VALORANT API
# Third-party docs: https://github.com/RumbleMike/ValorantClientAPI
# Implementation: https://github.com/RumbleMike/ValorantStreamOverlay


def _read_ranks() -> Dict[str, str]:
    with (DATA_DIR / "valorant" / "ranks.json").open() as fp:
        return cast(Dict[str, str], json.load(fp)['Ranks'])


_RANK_NAMES = _read_ranks()


class RiotAuthError(Exception):
    pass


class RiotAPIRegion(str, enum.Enum):
    NA = "na"  # North America
    EU = "eu"  # Europe
    AP = "ap"  # Asia Pacific
    KO = "ko"  # Korea


class RiotAPIClient:
    def __init__(
        self,
        session: ClientSession,
        region: RiotAPIRegion,
        username: str,
        password: str,
    ):
        self.session = session
        self.region = region
        self._username = username
        self._password = password

        self._access_token: Optional[str] = None
        self._id_token: Optional[str] = None
        self._entitlements_token: Optional[str] = None
        self._expires: Optional[datetime.datetime] = None

    def _are_tokens_valid(self) -> bool:
        if (
            self._access_token is None
            or self._id_token is None
            or self._entitlements_token is None
            or self._expires is None
        ):
            return False
        if datetime.datetime.utcnow() > self._expires:
            # Tokens have expired
            return False
        return True

    def _get_authorization_headers(self) -> Dict[str, str]:
        assert self._access_token is not None, "access_token exists"

        headers = dict()
        headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _get_full_headers(self) -> Dict[str, str]:
        assert self._entitlements_token is not None, "entitlements_token exists"

        headers = dict()
        headers.update(self._get_authorization_headers())
        headers["X-Riot-Entitlements-JWT"] = self._entitlements_token
        headers[
            "X-Riot-ClientPlatform"
        ] = "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9"
        return headers

    async def _do_authorization(self) -> None:
        # Based on https://github.com/RumbleMike/ValorantStreamOverlay/blob/4737044373e9e467468481f8965d27217260009b/Authentication.cs#L16-L28
        payload = {
            "client_id": "play-valorant-web-prod",
            "nonce": "1",
            "redirect_uri": "https://playvalorant.com/opt_in",
            "response_type": "token id_token",
            "scope": "account openid",
        }
        await self.session.post(
            "https://auth.riotgames.com/api/v1/authorization", json=payload
        )

    async def _update_access_token(self) -> None:
        payload = {
            "type": "auth",
            "username": self._username,
            "password": self._password,
        }
        async with self.session.put(
            "https://auth.riotgames.com/api/v1/authorization", json=payload
        ) as response:
            data = await response.json()
        if "error" in data:
            print("Error in _update_access_token:", data, file=sys.stderr)
            raise RiotAuthError(
                f'Got error {data.get("error", "(Unspecified)")} for response type {data.get("type", "(Unspecified)")}'
            )
        assert data["type"] == "response", "type is response"
        assert data["response"]["mode"] == "fragment", "response/mode is fragment"
        response_qs = urllib.parse.urlparse(
            data["response"]["parameters"]["uri"]
        ).fragment

        response_fields = urllib.parse.parse_qs(response_qs, strict_parsing=True)
        assert len(response_fields["access_token"]) == 1, "only one access_token"
        assert len(response_fields["id_token"]) == 1, "only one id_token"
        assert len(response_fields["expires_in"]) == 1, "only one expires_in"
        self._access_token = response_fields["access_token"][0]
        self._id_token = response_fields["id_token"][0]
        expires_in = datetime.timedelta(seconds=int(response_fields["expires_in"][0]))
        self._expires = datetime.datetime.utcnow() + expires_in

    async def _update_entitlement_token(self) -> None:
        assert self._access_token is not None, "access_token exists"

        async with self.session.post(
            "https://entitlements.auth.riotgames.com/api/token/v1",
            headers=self._get_authorization_headers(),
            json=dict(),
        ) as response:
            data = await response.json()
        self._entitlements_token = data["entitlements_token"]

    async def _update_tokens(self) -> None:
        await self._do_authorization()
        await self._update_access_token()
        await self._update_entitlement_token()

    @property
    def _pd_endpoint(self) -> str:
        return f"https://pd.{self.region.value}.a.pvp.net"

    @property
    def _shared_endpoint(self) -> str:
        return f"https://shared.{self.region.value}.a.pvp.net"

    async def refresh_tokens(self, force: bool = False) -> None:
        if force or not self._are_tokens_valid():
            await self._update_tokens()
            assert self._are_tokens_valid(), "tokens are valid after updating"

    async def get_userinfo(self) -> Dict[str, str]:
        # Refer: https://github.com/RumbleMike/ValorantStreamOverlay/blob/4737044373e9e467468481f8965d27217260009b/LogicHandler.cs#L109-L121
        await self.refresh_tokens()
        async with self.session.post(
            "https://auth.riotgames.com/userinfo",
            headers=self._get_authorization_headers(),
        ) as response:
            return cast(Dict[str, str], await response.json())

    async def get_mmr(
        self, player_id: str, start_index: int = 0, end_index: int = 20
    ) -> Dict[str, Any]:
        # Refer:
        # - https://github.com/RumbleMike/ValorantStreamOverlay/blob/4737044373e9e467468481f8965d27217260009b/RankDetection.cs#L37-L72
        # - https://github.com/RumbleMike/ValorantClientAPI/blob/master/Docs/PlayerMMR.md
        await self.refresh_tokens()
        async with self.session.get(
            f"{self._pd_endpoint}/mmr/v1/players/{player_id}/competitiveupdates?startIndex={start_index}&endIndex={end_index}",
            headers=self._get_full_headers(),
        ) as response:
            return cast(Dict[str, Any], json.loads(await response.text()))

    async def get_current_compet_stats(
        self, player_id: str
    ) -> Optional[Tuple[int, int, datetime.datetime]]:
        for start_index in range(0, 100, 20):
            mmr_data = await self.get_mmr(player_id, start_index, start_index + 20)
            assert (
                mmr_data["Subject"] == player_id
            ), "MMR data should belong to the player"
            for match in mmr_data["Matches"]:
                if (
                    match["TierAfterUpdate"] == 0
                    and match["TierBeforeUpdate"] == 0
                    and match["RankedRatingAfterUpdate"] == 0
                    and match["RankedRatingBeforeUpdate"] == 0
                ):
                    # Unrated match(?), skipping
                    continue
                return (
                    int(match["TierAfterUpdate"]),
                    int(match["RankedRatingAfterUpdate"]),
                    datetime.datetime.utcfromtimestamp(match["MatchStartTime"] / 1000),
                )
        return None


class Valorant(Cog):
    def __init__(self, bot: Elboto):
        self.bot = bot

        self._clients: Dict[RiotAPIRegion, RiotAPIClient] = dict()

    async def cog_check(self, ctx: Context) -> bool:
        # TODO: Open up access to public
        return await self.bot.is_owner(ctx.author)

    def cog_unload(self) -> None:
        for client in self._clients.values():
            self.bot.loop.create_task(client.session.close())

    async def cog_command_error(self, ctx: Context, error: CommandError) -> None:
        await ctx.reply(f"Error executing command: `{error}`")

    def _get_client(self, region: RiotAPIRegion) -> RiotAPIClient:
        if region not in self._clients:
            username, password = self.bot.config.valorant_creds[region]
            if username is None or password is None:
                raise CommandError(
                    f"Username or password is invalid for region {region}"
                )
            self._clients[region] = RiotAPIClient(
                ClientSession(), region, username, password
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
            await self._get_client(region).refresh_tokens(True)
            await ctx.message.add_reaction("\N{OK HAND SIGN}")

    @valo_admin.command()
    async def userinfo(self, ctx: Context, region: RiotAPIRegion) -> None:
        async with ctx.typing():
            data = await self._get_client(region).get_userinfo()
            await ctx.reply(f"""```json\n{json.dumps(data, indent=2)}\n```""")

    @valo.command()
    async def mmr(
        self,
        ctx: Context,
        region: RiotAPIRegion,
        player_id: str,
        start_index: int,
        end_index: int,
    ) -> None:
        async with ctx.typing():
            data = await self._get_client(region).get_mmr(
                player_id, start_index, end_index
            )
            data_io = io.BytesIO(json.dumps(data, indent=2).encode("UTF-8"))
            await ctx.reply(
                "See attachment", file=discord.File(data_io, f"mmr_{player_id}.json")
            )

    @valo.command()
    async def rank(self, ctx: Context, region: RiotAPIRegion, player_id: str) -> None:
        async with ctx.typing():
            data = await self._get_client(region).get_current_compet_stats(player_id)
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
