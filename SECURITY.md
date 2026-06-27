# Security

## Public-data boundary

This repository is designed to contain only source code and public market/news data.
Do not commit client materials, confidential deal information, MNPI, personal data,
broker exports, API keys, bot tokens, or local `.env` files.

## Secrets

Store optional Telegram credentials in GitHub Actions Secrets or a local `.env` file:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

If a secret is committed, revoke it immediately, create a replacement, and remove it
from Git history before making the repository public.

## Reporting a vulnerability

Use the repository's private GitHub Security Advisory flow. Do not publish a working
exploit or credentials in a public issue.
