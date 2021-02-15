# Elboto

Eloston's Discord bot

## Setup

1. Create `config.py` in the root directory of the bot, using this template:

```py
command_prefix = '>'
client_id = 'CLIENT_ID_HERE'
# DO NOT LEAK THE BOT TOKEN
token = 'BOT_TOKEN_HERE'

# Credentials for Riot "backend" users to access data for a given region
valorant_creds = {
    # Specify (None, None) to not provide an account for a region
    "na": ("username", "password"),  # North America
    "eu": (None, None),  # Europe
    "ap": (None, None),  # Asia Pacific
    "ko": (None, None),  # Korea
}

# Iterable of Discord Role name (as str) or Role ID (as int)
valorant_access_roles = ("RoleName", 123456789012345678)
```

Launch:

```sh
python3 main.py
```

NOTE: This will create a `runtime/` directory at the root of the repository to store long-term data (i.e. beyond one bot session).

## Development

This is how I setup the bot.

First-time setup:

```sh
pipx install poetry
poetry install
```

My editor is VS Code. Launching VS Code:

```sh
poetry shell
codium .
```