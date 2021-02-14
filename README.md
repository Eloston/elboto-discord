# Elboto

Eloston's Discord bot

## Setup

1. Create `config.py` in the root directory of the bot, using this template:

```py
command_prefix = '>'
client_id = 'CLIENT_ID_HERE'
# DO NOT LEAK THE BOT TOKEN
token = 'BOT_TOKEN_HERE'
```

Launch:

```sh
python3 main.py
```

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