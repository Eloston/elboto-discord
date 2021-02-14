# -*- coding: utf-8 -*-

import sys
from typing import Dict, Tuple

from discord.ext.typed_commands import Bot

_DESCRIPTION = """
Eloston's Discord bot
"""
_STARTUP_EXTENSIONS = ("elboto.cogs.admin", "elboto.cogs.valorant", "elboto.cogs.extra")


class BotConfig:
    command_prefix: str
    token: str
    client_id: str
    valorant_creds: Dict[str, Tuple[str, str]]


class Elboto(Bot):
    def __init__(self, config: BotConfig):
        self.config = config

        super().__init__(
            command_prefix=self.config.command_prefix, description=_DESCRIPTION
        )

        for extension in _STARTUP_EXTENSIONS:
            try:
                self.load_extension(extension)
            except Exception as exc:
                print(f"Failed to load extension {extension}.", file=sys.stderr)
                print(exc)

    def start_bot(self) -> None:
        self.run(self.config.token, reconnect=True)
