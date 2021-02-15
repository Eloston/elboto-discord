# -*- coding: utf-8 -*-

import asyncio
import datetime
import enum
import json
import sys
import urllib.parse
from typing import Any, Awaitable, Dict, Optional, Tuple, cast

from aiohttp import ClientSession


class RiotAuthError(Exception):
    pass


class RiotAPIError(Exception):
    pass


class RiotAPIRegion(str, enum.Enum):
    NA = "na"  # North America
    EU = "eu"  # Europe
    AP = "ap"  # Asia Pacific
    KO = "ko"  # Korea


class RiotAPIClient:
    # Third-party docs: https://github.com/RumbleMike/ValorantClientAPI
    # Implementation: https://github.com/RumbleMike/ValorantStreamOverlay

    def __init__(
        self,
        region: RiotAPIRegion,
        username: str,
        password: str,
    ):
        self.region = region
        self._username = username
        self._password = password

        self._access_token: Optional[str] = None
        self._id_token: Optional[str] = None
        self._entitlements_token: Optional[str] = None
        self._expires: Optional[datetime.datetime] = None

        self._refresh_lock = asyncio.Lock()

        self._make_session()

    def _make_session(self) -> None:
        self.session = ClientSession()

    def unload(self) -> Awaitable:
        return self.session.close()

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
        await self.session.close()
        self._make_session()
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
        async with self._refresh_lock:
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
        self, puuid: str, start_index: int = 0, end_index: int = 20
    ) -> Dict[str, Any]:
        # Refer:
        # - https://github.com/RumbleMike/ValorantStreamOverlay/blob/4737044373e9e467468481f8965d27217260009b/RankDetection.cs#L37-L72
        # - https://github.com/RumbleMike/ValorantClientAPI/blob/master/Docs/PlayerMMR.md
        await self.refresh_tokens()
        async with self.session.get(
            f"{self._pd_endpoint}/mmr/v1/players/{puuid}/competitiveupdates?startIndex={start_index}&endIndex={end_index}",
            headers=self._get_full_headers(),
        ) as response:
            return cast(Dict[str, Any], json.loads(await response.text()))

    async def get_current_compet_stats(
        self, puuid: str
    ) -> Optional[Tuple[int, int, datetime.datetime]]:
        start_index = 0
        for num_records in [5, 10, 20, 20]:
            mmr_data = await self.get_mmr(
                puuid, start_index, start_index + num_records - 1
            )
            if "errorCode" in mmr_data:
                raise RiotAPIError(
                    f"Error retrieving MMR data in range {start_index}->{start_index+num_records}: {mmr_data}"
                )
            if "Matches" not in mmr_data:
                print(f"No Matches key in MMR data (puuid: {puuid}): {mmr_data}")
                raise RiotAPIError(
                    f"Did not find Matches key in MMR data range {start_index}->{start_index+num_records}"
                )
            if not mmr_data["Matches"]:
                # No match data found
                raise RiotAPIError(
                    f"Did not find any matches in MMR data range {start_index}->{start_index+num_records}"
                )
            start_index += num_records
            assert mmr_data["Subject"] == puuid, "MMR data should belong to the player"
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


class Henrik3APIError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"Henrik-3 API error {code}: {message}")
        self.code = code
        self.message = message


class Henrik3APIClient:
    # Third-party service: https://github.com/Henrik-4/unofficial-valorant-api

    _endpoint = "https://api.henrikdev.xyz"

    def get_puuid_url(self, name: str, tag: str) -> str:
        return f"{self._endpoint}/valorant/v1/puuid/{name}/{tag}"

    async def get_puuid(self, name: str, tag: str) -> str:
        async with ClientSession() as session:
            async with session.get(self.get_puuid_url(name, tag)) as response:
                data = await response.json()
            if data["status"] != "200":
                raise Henrik3APIError(int(data["status"]), str(data["message"]))
            assert "data" in data, f"Could not find 'data' in data: {data}"
            data = data["data"]
            assert "puuid" in data, f"Could not find 'puuid' in payload: {data}"
            puuid = data["puuid"]
            assert isinstance(puuid, str), f"puuid is not a string: {puuid}"
            return puuid
